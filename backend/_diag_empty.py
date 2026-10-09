"""验证「模型返回内容为空」的成因：max_tokens 被 reasoning_content 吃光。

运行：python _diag_empty.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Claim  # noqa: E402
from app.services import auditor, llm  # noqa: E402

db = SessionLocal()
claim = db.get(Claim, 50)
preview = auditor.build_material_preview(claim)
messages = [
    {"role": "system", "content": auditor.AUDIT_SYSTEM},
    {"role": "user", "content": auditor.AUDIT_USER
     .replace("{TYPE_STANDARD}", auditor._type_standard_text(claim.claim_type))
     .replace("{claim_json}", json.dumps(auditor.build_claim_dict(claim), ensure_ascii=False))
     .replace("{text_preview}", preview or "（无材料文本）")},
]
db.close()

cfg = llm.get_active_config()
print(f"model={cfg['model']}  prompt 字符数={sum(len(m['content']) for m in messages)}")

for mt in (1500, 2500, 3500, 5000):
    payload = {"model": cfg["model"], "messages": messages,
               "temperature": 0.1, "max_tokens": mt,
               "response_format": {"type": "json_object"}}
    r = httpx.post(f"{cfg['base_url']}/chat/completions",
                   headers={"Authorization": f"Bearer {cfg['api_key']}"},
                   json=payload, timeout=config.AI_TIMEOUT)
    if r.status_code != 200:
        print(f"max_tokens={mt}: HTTP {r.status_code} {r.text[:150]}")
        continue
    j = r.json()
    ch = (j.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    content = msg.get("content") or ""
    u = j.get("usage") or {}
    rt = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
    print(f"max_tokens={mt:<5} finish={ch.get('finish_reason'):<7} "
          f"reasoning_tokens={rt} content_len={len(content)} "
          f"→ {'❌ content 为空（正是报错情形）' if not content.strip() else 'ok'}")
print("\n=========== 结束 ===========")
