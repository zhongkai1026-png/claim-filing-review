"""修正 GLM-5.2 配置（正确 base_url=/v1 + 小写模型名）并测试。"""
import sys
import time

import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = "sk-JeM7UsOsdTYODMij4glo1IlwqlKUshWSOk8sSuciEbDHwmUW"
BASE = "https://newapi.web.azshentong.com/v1"
MODEL = "glm-5.2"
NAME = "GLM-5.2"

print("=" * 56)
print("  修正 AI 配置并测试")
print("=" * 56)

# 1. 更新数据库配置
from app.database import SessionLocal, init_db
from app.models import AIConfig

init_db()
db = SessionLocal()
try:
    cfg = db.query(AIConfig).filter(AIConfig.name == NAME).first()
    if not cfg:
        cfg = AIConfig(name=NAME)
        db.add(cfg)
    cfg.base_url = BASE
    cfg.api_key = KEY
    cfg.model = MODEL
    db.query(AIConfig).update({AIConfig.is_active: 0})
    cfg.is_active = 1
    db.commit()
    db.refresh(cfg)
    print(f"[1] 配置已更新：{cfg.base_url} / {cfg.model}（已激活）")
finally:
    db.close()

# 2. 测试连接（重试，避免瞬时限流）
print("\n[2] 测试连接（含重试）")
for attempt in range(1, 6):
    try:
        r = httpx.post(
            f"{BASE}/chat/completions",
            headers={"Authorization": f"Bearer {KEY}"},
            json={"model": MODEL,
                  "messages": [{"role": "user", "content": "请回复：连接成功"}],
                  "max_tokens": 20},
            timeout=60,
        )
        if r.status_code == 200:
            j = r.json()
            content = j["choices"][0]["message"]["content"]
            print(f"    第{attempt}次尝试 -> ✅ HTTP 200")
            print(f"    模型回复: {content[:80]}")
            print("\n✅ 连接成功！配置已生效。")
            break
        else:
            msg = ""
            try:
                msg = r.json().get("error", {}).get("message", "")
            except Exception:
                pass
            print(f"    第{attempt}次尝试 -> HTTP {r.status_code} {msg[:100]}")
            time.sleep(5)
    except Exception as e:
        print(f"    第{attempt}次尝试 -> ERROR {e}")
        time.sleep(5)
else:
    print("\n❌ 多次尝试仍失败，可能是账户限流（429）或额度问题，请稍后再试")
