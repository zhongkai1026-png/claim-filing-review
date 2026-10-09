"""AI 审查标准升级验证。

第一部分（离线）：类型匹配逻辑 + 真实台账命中率
第二部分（在线）：临时项目跑两笔真实 AI 审查，验证注入标准、提示词版本与类型化条款是否真的进了意见

运行：python _test_audit_standards.py
"""
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
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
        b = "----stdtest"
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


print("== 第一部分：类型匹配逻辑（离线） ==")
cases = [
    (("借贷", "", ""), ["借贷"], "债权类型=借贷"),
    (("", "借贷", ""), ["借贷"], "债权种类=借贷（回退）"),
    (("", "工程款", ""), ["工程款"], "债权种类=工程款（回退）"),
    (("", "金融债权", ""), ["金融"], "债权种类=金融债权（同义归一）"),
    (("普通债权", "工程债权", ""), ["工程款"], "类型写普通债权时按种类回退"),
    (("", "职工", ""), ["职工"], "债权种类=职工"),
    (("", "", "本合同为建设工程施工合同，实际施工人主张工程价款优先受偿权"), ["工程款"],
     "无台账类型时按材料特征词兜底"),
    (("", "", "债权人主张行使取回权，标的物为融资租赁物"), ["取回权"], "材料出现取回权"),
    (("", "金融", "本债权为金融不良资产包受让取得"), ["金融不良"], "金融不良优先于金融"),
]
for (ct, cc, mat), want, label in cases:
    got = A.match_claim_types(ct, cc, mat)
    ok(got[:len(want)] == want, f"{label} → {want}", got)

print("\n  真实台账命中率（32 笔）：")
import sqlite3  # noqa: E402
conn = sqlite3.connect(Path(__file__).parent / "data" / "claims.db")
rows = conn.execute("select claim_type, claim_category, "
                    "(select group_concat(ocr_text,' ') from claim_files f where f.claim_id=c.id) "
                    "from claims c").fetchall()
conn.close()
hit = {}
for ct, cc, mat in rows:
    for k in A.match_claim_types(ct, cc, (mat or "")[:4000]):
        hit[k] = hit.get(k, 0) + 1
total_hit = sum(1 for ct, cc, mat in rows if A.match_claim_types(ct, cc, (mat or "")[:4000]))
print(f"    命中类型分布：{hit}")
ok(total_hit >= 20, f"至少 20 笔命中类型化标准（实际 {total_hit}/32）", total_hit)
ok("工程款" in hit and "借贷" in hit and "金融" in hit, "工程款/借贷/金融均有用例命中", hit)

print("\n  提示词体量：")
full, core = len(A.AUDIT_SYSTEM), len(A.build_audit_system(A.GENERAL_RULES_CORE))
print(f"    full={full} 字符 / basic={core} 字符 / 类型标准 {len(A.TYPE_STANDARDS)} 类")
ok(full > core, "full 档提示词内容多于 basic 档（可用 AI_PROMPT_PROFILE=basic 回退）")
ok(len(A.TYPE_STANDARDS) == 11, "类型化标准扩到 11 类", list(A.TYPE_STANDARDS))
ok("18 个月" in A.TYPE_STANDARDS["工程款"] and "LPR 的 4 倍" in A.TYPE_STANDARDS["借贷"],
   "关键差异化条款在位（工程款18个月 / 借贷LPR4倍）")

print("\n== 第二部分：真实 AI 审查（在线） ==")
for p in req("GET", "/api/projects"):
    if p["name"].startswith("审查标准测试"):
        for cl in req("GET", f"/api/claims?project_id={p['id']}"):
            req("DELETE", f"/api/claims/{cl['id']}")
        req("DELETE", f"/api/projects/{p['id']}")
pid = req("POST", "/api/projects", json_body={
    "name": "审查标准测试（自动清理）", "case_no": "TEST-STD"})["id"]

samples = [
    ("借贷", "借款合同\n出借人：张三\n借款人：测试公司\n借款金额：500000元\n"
            "约定年利率：36%\n逾期违约金：每日千分之一\n",
     ["LPR", "四倍", "4倍", "民间借贷"], "借贷"),
    ("工程款", "建设工程施工合同\n发包人：测试公司\n承包人：某建筑公司\n"
              "工程结算价款：12000000元\n竣工日期：2023年3月，应付日期2023年5月\n"
              "另主张利息及违约金2000000元\n",
     ["18个月", "十八个月", "优先受偿"], "工程款"),
]
cids = []
try:
    for i, (cat, text, _kw, _t) in enumerate(samples, start=1):
        c = req("POST", f"/api/projects/{pid}/upload",
                files=[(f"{cat}材料{i}.txt", text.encode("utf-8"))])
        cid = c["id"]
        cids.append(cid)
        req("PUT", f"/api/claims/{cid}", json_body={
            "name": f"{cat}测试债权人", "claim_category": cat,
            "principal": 500000 if cat == "借贷" else 12000000,
            "claim_amount": 500000 if cat == "借贷" else 14000000,
            "claim_type": ""})
    time.sleep(8)

    for (cat, _text, keywords, want_std) in samples:
        cid = cids[samples.index((cat, _text, keywords, want_std))]
        req("POST", f"/api/claims/{cid}/ai-audit")
        a = None
        for _ in range(60):
            time.sleep(5)
            a = req("GET", f"/api/claims/{cid}/audit")
            if a and a.get("ai_status") in ("done", "failed"):
                break
        print(f"\n  —— {cat} 债权（claim {cid}）——")
        ok(a.get("ai_status") == "done", "AI 审查完成", a.get("ai_status"))
        ok(a.get("prompt_version") == A.PROMPT_VERSION,
           f"记录提示词版本 {A.PROMPT_VERSION}", a.get("prompt_version"))
        ok(want_std in (a.get("injected_standards") or ""),
           f"注入标准含「{want_std}」", a.get("injected_standards"))
        op = json.loads(a.get("ai_opinion") or "{}")
        blob = json.dumps(op, ensure_ascii=False)
        ok(len(op.get("review_process") or []) == 7, "决策树 7 级完整",
           len(op.get("review_process") or []))
        found = [k for k in keywords if k in blob]
        ok(bool(found), f"意见中出现类型化条款关键词 {keywords}", found)
        refs = op.get("standard_refs") or []
        ok(bool(refs), f"standard_refs 记录了引用的标准条目（{want_std}-N）",
           {"standard_refs": refs, "含行内标注": "依据：" in blob})
        ok(any(str(r).startswith(want_std) for r in refs),
           f"引用的条目属于 {want_std} 标准", refs)
        print(f"     结论：{op.get('conclusion')} / {op.get('review_result')}"
              f"｜法条 {len(op.get('legal_basis') or [])} 条"
              f"｜引用标准 {refs}｜命中关键词 {found}")
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
print("✅ AI 审查标准升级全部通过")
