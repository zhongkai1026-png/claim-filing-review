"""复现真实失败债权：取 audit_results 中 ai_status=failed 的债权，
用与生产一致的 prompt（含真实材料文本）+ max_tokens=5000 重放，打印 finish_reason。

运行：python _diag_fail.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AuditResult, Claim  # noqa: E402
from app.services import auditor, llm  # noqa: E402

db = SessionLocal()
rows = db.query(AuditResult).filter(AuditResult.ai_status == "failed").all()
print(f"== ai_status=failed 记录数：{len(rows)} ==")
for r in rows[:10]:
    c = db.get(Claim, r.claim_id)
    print(f"claim_id={r.claim_id} 编号={getattr(c,'claim_no',None)} "
          f"名称={getattr(c,'name',None)!r} model={r.ai_model!r}")
    print(f"  ai_error = {r.ai_error!r}")

print("\n== 仍处于 running 的（可能是超时/线程已死）==")
for r in db.query(AuditResult).filter(AuditResult.ai_status == "running").all():
    print(f"claim_id={r.claim_id}")

# 选一个失败债权做重放，否则选材料最多的
target = rows[0] if rows else None
if target is None:
    print("\n（无失败记录，改为选取材料文本最长的债权做压力重放）")
    best, best_len = None, 0
    for c in db.query(Claim).all():
        ln = sum(len(f.ocr_text or "") for f in c.files)
        if ln > best_len:
            best, best_len = c, ln
    target_claim, target_len = best, best_len
else:
    target_claim = db.get(Claim, target.claim_id)
    target_len = sum(len(f.ocr_text or "") for f in target_claim.files)

if not target_claim:
    sys.exit("无可重放债权")

print(f"\n重放对象：claim_id={target_claim.id} {target_claim.name!r} "
      f"材料原始文本合计 {target_len} 字符，文件数 {len(target_claim.files)}")

preview = auditor.build_material_preview(target_claim)
claim_json = json.dumps(auditor.build_claim_dict(target_claim), ensure_ascii=False)
messages = [
    {"role": "system", "content": auditor.AUDIT_SYSTEM},
    {"role": "user", "content": auditor.AUDIT_USER
     .replace("{TYPE_STANDARD}", auditor._type_standard_text(target_claim.claim_type))
     .replace("{claim_json}", claim_json)
     .replace("{text_preview}", preview or "（无材料文本，仅有台账登记信息）")},
]
print("注入材料的 preview 字符数：", len(preview))
print("prompt 总字符数：", sum(len(m["content"]) for m in messages))
db.close()

cfg = llm.get_active_config()
print(f"\n使用配置：model={cfg['model']} base_url={cfg['base_url']}")


def call(label, max_tokens, json_mode=True):
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": 0.1, "max_tokens": max_tokens}
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    print(f"\n===== {label}（max_tokens={max_tokens}, json_mode={json_mode}）=====")
    try:
        r = httpx.post(f"{cfg['base_url']}/chat/completions",
                       headers={"Authorization": f"Bearer {cfg['api_key']}"},
                       json=payload, timeout=config.AI_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        print("EXCEPTION:", type(e).__name__, e)
        return
    print("HTTP", r.status_code)
    if r.status_code != 200:
        print(r.text[:500])
        return
    j = r.json()
    ch = (j.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = msg.get("content") or ""
    print("finish_reason :", ch.get("finish_reason"))
    u = j.get("usage") or {}
    print("usage         :", json.dumps(u, ensure_ascii=False))
    print("reasoning_tokens:", (u.get("completion_tokens_details") or {}).get("reasoning_tokens"))
    print("content 长度  :", len(content))
    print("reasoning 长度:", len(msg.get("reasoning_content") or ""))
    print("content 前120 :", repr(content[:120]))
    if not content.strip():
        print(">>> 复现成功：content 为空，与生产报错一致")


call("A: 与生产完全一致", 5000)
call("B: 放宽 max_tokens", 16000)
print("\n=========== 复现结束 ===========")
