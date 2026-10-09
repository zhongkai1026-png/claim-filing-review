"""AI 审查失败诊断：打印激活配置 + 原始响应（finish_reason / usage / reasoning_content）。

运行：python _diag_llm.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import httpx  # noqa: E402

from app import config  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import AIConfig  # noqa: E402
from app.services import auditor, llm  # noqa: E402

db = SessionLocal()
print("== ai_configs 表全部配置 ==")
for c in db.query(AIConfig).all():
    print(f"id={c.id} name={c.name!r} model={c.model!r} base_url={c.base_url!r} "
          f"active={c.is_active} key={ (c.api_key or '')[:8] }****")
db.close()

cfg = llm.get_active_config()
print("\n== 激活配置 ==")
print(json.dumps({**cfg, "api_key": (cfg or {}).get("api_key", "")[:8] + "****"}
                 if cfg else None, ensure_ascii=False, indent=2))
print("AI_TIMEOUT =", config.AI_TIMEOUT)
if not cfg:
    sys.exit("无激活配置")


def raw_call(label, payload):
    print(f"\n===== {label} =====")
    print("payload keys:", list(payload.keys()))
    try:
        r = httpx.post(f"{cfg['base_url']}/chat/completions",
                       headers={"Authorization": f"Bearer {cfg['api_key']}"},
                       json=payload, timeout=config.AI_TIMEOUT)
    except Exception as e:  # noqa: BLE001
        print("EXCEPTION:", type(e).__name__, e)
        return None
    print("HTTP", r.status_code)
    try:
        j = r.json()
    except Exception:  # noqa: BLE001
        print("非 JSON 响应:", r.text[:500])
        return None
    if r.status_code != 200:
        print(json.dumps(j, ensure_ascii=False)[:800])
        return None
    ch = (j.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    print("finish_reason :", ch.get("finish_reason"))
    print("usage         :", json.dumps(j.get("usage"), ensure_ascii=False))
    print("content 长度  :", len(msg.get("content") or ""))
    print("content 前200 :", repr((msg.get("content") or "")[:200]))
    print("reasoning_content 长度:", len(msg.get("reasoning_content") or ""))
    for k in msg:
        if k not in ("content", "reasoning_content", "role"):
            print(f"message.{k} =", repr(msg[k])[:200])
    return j


# 1) 最小连通性
raw_call("① 最小调用（无 json_mode）", {
    "model": cfg["model"],
    "messages": [{"role": "user", "content": "请回复：连接成功"}],
    "temperature": 0,
    "max_tokens": 50,
})

# 2) 与生产完全一致的审查调用（json_mode + max_tokens 5000）
claim_json = '{"债权编号":"PC-001","债权人名称":"XX建材集团有限公司","申报本金":856000.00,' \
             '"申报利息":12000.50,"申报其他":3000.00,"申报总额":871000.50,"债权类型":"购销",' \
             '"申报债权种类":"购销","申报债权性质":"普通债权","涉诉涉执":"是"}'
material = "【材料：购销合同.pdf】\nXX建材集团有限公司与债务人于2022年3月签订购销合同，" \
           "货款本金人民币 856000.00 元，约定逾期利息按年利率 8% 计算。"
messages = [
    {"role": "system", "content": auditor.AUDIT_SYSTEM},
    {"role": "user", "content": auditor.AUDIT_USER
     .replace("{TYPE_STANDARD}", auditor._type_standard_text("购销"))
     .replace("{claim_json}", claim_json)
     .replace("{text_preview}", material)},
]
print("\n审查 prompt 字符数：", sum(len(m["content"]) for m in messages))

raw_call("② 审查调用（json_mode=True, max_tokens=5000）", {
    "model": cfg["model"], "messages": messages,
    "temperature": 0.1, "max_tokens": 5000,
    "response_format": {"type": "json_object"},
})

raw_call("③ 审查调用（json_mode=False, max_tokens=5000）", {
    "model": cfg["model"], "messages": messages,
    "temperature": 0.1, "max_tokens": 5000,
})

raw_call("④ 审查调用（json_mode=False, max_tokens=16000）", {
    "model": cfg["model"], "messages": messages,
    "temperature": 0.1, "max_tokens": 16000,
})

print("\n=========== 诊断结束 ===========")
