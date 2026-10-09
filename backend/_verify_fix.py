"""验证修复：空内容 / 截断的报错是否准确（不再误报为「模型名或 JSON 支持」问题）。

用假响应打桩覆盖 3 种网关返回形态，再对真实模型跑一次完整调用。

运行：python _verify_fix.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import config  # noqa: E402
from app.services import llm  # noqa: E402

print("AI_MAX_TOKENS =", config.AI_MAX_TOKENS, "| AI_TIMEOUT =", config.AI_TIMEOUT)
cfg = llm.get_active_config()
print("激活模型:", cfg["model"], "|", cfg["base_url"], "\n")

# ---------- 打桩：模拟网关卡住/截断的返回 ----------
real_post = llm.httpx.post


class FakeResp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p

    text = ""


def make(choice):
    return FakeResp({"choices": [choice]})


CASES = [
    ("思考吃满额度 → 正文为空（原报错情形）", make({
        "finish_reason": "length",
        "message": {"role": "assistant", "content": "",
                    "reasoning_content": "……（思考内容）"}})),
    ("只返回思考内容，无正文", make({
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": "",
                    "reasoning_content": "……（思考内容）"}})),
    ("网关返回真空内容（模型不可用/额度耗尽）", make({
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": ""}})),
]

print("=== 打桩验证错误提示 ===")
for label, fake in CASES:
    llm.httpx.post = lambda *a, **k: fake  # noqa: ARG005
    out = llm.chat([{"role": "user", "content": "x"}], json_mode=True,
                   max_tokens=5000)
    print(f"[{label}]\n  返回={out}\n  提示={llm.get_last_error()}\n")

# 截断但正文非空 → 应返回正文（交给 chat_json 处理），并记录告警
llm.httpx.post = lambda *a, **k: make({  # noqa: ARG005
    "finish_reason": "length",
    "message": {"role": "assistant", "content": '{"conclusion":"认可"'}})
out = llm.chat([{"role": "user", "content": "x"}], json_mode=True, max_tokens=5000)
print(f"[正文被截断但非空]\n  返回={out!r}\n  提示={llm.get_last_error() or '（无）'}\n")
data = llm.chat_json([{"role": "user", "content": "x"}], max_tokens=5000)
print(f"  chat_json 结果={data}\n  提示={llm.get_last_error()}\n")

llm.httpx.post = real_post

print("=== 真实调用（当前激活模型）===")
text = llm.chat([{"role": "user", "content": '只输出 JSON：{"conclusion":"认可"}'}],
                json_mode=True, temperature=0.1)
print("返回:", (text or "")[:80])
print("提示:", llm.get_last_error() or "（无）")
print("\n=========== 验证结束 ===========")
