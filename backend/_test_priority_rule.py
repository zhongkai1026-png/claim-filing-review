"""AI 审查「数据优先级规则」验证。

规则：初审/编辑（或人工复核）确认过的债权 → AI 审查以台账数据为优先依据，材料仅作核验；
      未经人工确认的 → 材料原文优先，并提示需人工核对。
验证点：① 台账数据状态标注；② 提示词规则已就位且与旧规则不冲突；
        ③ 保存初审/编辑会写入 verified_at；④ 真实审查仍能跑通。

运行：python _test_priority_rule.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Claim  # noqa: E402
from app.services import auditor as A  # noqa: E402

BASE = "http://127.0.0.1:8000"
fails = []


def ok(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  → {extra}"))
    if not cond:
        fails.append(label)


def req(method, path, json_body=None, files=None):
    headers, body = {}, None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif files:
        b = "----priotest"
        parts = []
        for name, content in files:
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="files"; '
                         f'filename="{name}"\r\n\r\n'.encode() + content + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        body = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=300) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else None


print("== 1. 提示词规则（离线） ==")
sys_prompt = A.AUDIT_SYSTEM
ok("数据优先级规则" in sys_prompt, "system 提示词含【数据优先级规则】")
ok("已人工初审/编辑确认" in sys_prompt and "台账数据优先" in sys_prompt,
   "明确人工确认后台账数据优先")
ok("系统解析预填" in sys_prompt and "材料原文优先" in sys_prompt,
   "未人工确认时材料原文优先")
ok("以材料原件为准" not in sys_prompt,
   "旧的“台账与材料不一致时以材料为准”已移除（避免规则冲突）")

print("\n== 2. 台账数据状态标注 ==")
db = SessionLocal()
c_unver = db.query(Claim).filter(Claim.verified_at.is_(None)).first()
c_ver = db.query(Claim).filter(Claim.verified_at.isnot(None)).first()
d_unver = A.build_claim_dict(c_unver) if c_unver else {}
d_ver = A.build_claim_dict(c_ver) if c_ver else {}
ok("台账数据状态" in d_unver, "台账 JSON 新增「台账数据状态」字段")
ok("系统解析预填" in d_unver.get("台账数据状态", ""),
   f"未确认债权标注为“系统解析预填”（claim {c_unver.id if c_unver else '-'}）",
   d_unver.get("台账数据状态"))
ok(c_ver is not None and "已人工" in d_ver.get("台账数据状态", ""),
   f"已确认债权标注为“已人工确认”（claim {c_ver.id if c_ver else '-'}）",
   d_ver.get("台账数据状态"))
db.close()

print("\n== 3. 初审/编辑保存写入 verified_at（在线，需服务为新代码） ==")
for p in req("GET", "/api/projects"):
    if p["name"].startswith("优先级测试"):
        for cl in req("GET", f"/api/claims?project_id={p['id']}"):
            req("DELETE", f"/api/claims/{cl['id']}")
        req("DELETE", f"/api/projects/{p['id']}")
pid = req("POST", "/api/projects", json_body={
    "name": "优先级测试（自动清理）", "case_no": "TEST-PRIO",
    "accept_date": "2024-11-18"})["id"]
cid = req("POST", f"/api/projects/{pid}/upload",
          files=[("合同.txt", "借款合同\n出借人：测试\n本金：100000元\n申报时间2020年8月18日\n"
                            .encode("utf-8"))])["id"]
try:
    time.sleep(6)
    c0 = req("GET", f"/api/claims/{cid}")
    ok("verified_at" in c0, "接口已暴露 verified_at（服务为新代码）")
    ok(not c0.get("verified_at"), "新上传、未编辑的债权 verified_at 为空", c0.get("verified_at"))
    c1 = req("PUT", f"/api/claims/{cid}", json_body={"name": "测试债权人", "principal": 120000})
    ok(bool(c1.get("verified_at")), "初审/编辑保存后写入 verified_at", c1.get("verified_at"))
    ok(c1["status"] == "registered", "保存即登记仍然生效", c1["status"])

    print("\n== 4. 真实 AI 审查（确认规则不阻断流程） ==")
    req("POST", f"/api/claims/{cid}/ai-audit")
    a = None
    for _ in range(40):
        time.sleep(5)
        a = req("GET", f"/api/claims/{cid}/audit")
        if a and a.get("ai_status") in ("done", "failed"):
            break
    ok(a.get("ai_status") == "done", "AI 审查完成", a.get("ai_status"))
    ok("破产受理日" in (a.get("injected_case_info") or ""),
       "审查记录含本次注入的案件信息（含破产受理日）", (a.get("injected_case_info") or "")[:80])
    op = json.loads(a.get("ai_opinion") or "{}")
    ok(len(op.get("review_process") or []) == 7, "决策树 7 级完整",
       len(op.get("review_process") or []))
    blob = json.dumps(op, ensure_ascii=False)
    ok(("台账" in blob) or ("材料" in blob), "意见中体现了台账/材料的口径说明")
    print("     结论：", op.get("conclusion"), "/", op.get("review_result"))
    print("     摘要：", str(op.get("summary"))[:110])
finally:
    print("\n== 清理 ==")
    for cl in req("GET", f"/api/claims?project_id={pid}"):
        req("DELETE", f"/api/claims/{cl['id']}")
    req("DELETE", f"/api/projects/{pid}")
    ok(not [x for x in req("GET", "/api/projects") if x["id"] == pid], "临时项目已删除")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 数据优先级规则全部通过")
