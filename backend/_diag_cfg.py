"""对比两个 AI 配置的实际返回（当前激活的 Deepseek-flash 与未激活的 GLM-5.2 代理），
并列出全部审查记录的错误信息。

运行：python _diag_cfg.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AIConfig, AuditResult, Claim  # noqa: E402

db = SessionLocal()
print("== 全部审查记录（claim / status / model / error）==")
for r in db.query(AuditResult).all():
    c = db.get(Claim, r.claim_id)
    print(f"claim_id={r.claim_id:<4} {getattr(c,'claim_no','')!s:<8} "
          f"status={r.ai_status or '-':<8} model={r.ai_model or '-':<12} "
          f"error={ (r.ai_error or '')[:90]!r}")

cfgs = db.query(AIConfig).all()
db.close()

MSGS = [
    {"role": "system", "content": "你是债权审查专家。只输出 JSON。"},
    {"role": "user", "content": "请输出 JSON：{\"conclusion\":\"认可\",\"summary\":\"一句话\"}"},
]

for c in cfgs:
    print(f"\n===== 配置 id={c.id} name={c.name!r} model={c.model!r} active={c.is_active} =====")
    print(f"base_url={c.base_url}")
    for json_mode in (True, False):
        payload = {"model": c.model, "messages": MSGS,
                   "temperature": 0.1, "max_tokens": 800}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        try:
            r = httpx.post(f"{c.base_url.rstrip('/')}/chat/completions",
                           headers={"Authorization": f"Bearer {c.api_key}"},
                           json=payload, timeout=config.AI_TIMEOUT)
        except Exception as e:  # noqa: BLE001
            print(f"  json_mode={json_mode}: EXCEPTION {type(e).__name__}: {e}")
            continue
        tag = f"  json_mode={json_mode}: "
        if r.status_code != 200:
            print(tag + f"HTTP {r.status_code} {r.text[:200]}")
            continue
        j = r.json()
        ch = (j.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        content = msg.get("content") or ""
        print(tag + f"HTTP 200 finish={ch.get('finish_reason')} "
                    f"content_len={len(content)} "
                    f"reasoning_len={len(msg.get('reasoning_content') or '')} "
                    f"usage={json.dumps(j.get('usage'), ensure_ascii=False)}")
        print("      content:", repr(content[:200]))
print("\n=========== 对比结束 ===========")
