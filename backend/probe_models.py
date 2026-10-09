"""列出中转站可用模型，并测试 GLM 相关模型名。"""
import sys
import httpx

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = "sk-JeM7UsOsdTYODMij4glo1IlwqlKUshWSOk8sSuciEbDHwmUW"
BASE = "https://newapi.web.azshentong.com"

# 1. 列出模型
for path in ("/v1/models", "/models"):
    try:
        r = httpx.get(BASE + path, headers={"Authorization": f"Bearer {KEY}"},
                      timeout=30)
        ct = r.headers.get("content-type", "")
        print(f"--- GET {path} -> HTTP {r.status_code}  ct={ct}")
        if r.status_code == 200 and "json" in ct:
            j = r.json()
            models = sorted(m.get("id", "") for m in j.get("data", []))
            print(f"    模型数量: {len(models)}")
            for m in models:
                print("    ", m)
        else:
            print("    body[:300]:", r.text[:300])
    except Exception as e:
        print(f"--- GET {path} -> ERROR {e}")
    print()

# 2. 测试候选模型名（GLM 系列）
candidates = ["GLM-5.2", "glm-5.2", "glm-4.5", "glm-4-plus", "glm-4-flash",
              "GLM-4.5", "glm-4", "chatglm_turbo", "glm-4v"]
print("=" * 50)
print("候选模型名测试（POST /v1/chat/completions）")
for m in candidates:
    try:
        r = httpx.post(BASE + "/v1/chat/completions",
                       headers={"Authorization": f"Bearer {KEY}"},
                       json={"model": m,
                             "messages": [{"role": "user", "content": "hi"}],
                             "max_tokens": 5},
                       timeout=30)
        ok = r.status_code == 200
        print(f"    {m:16s} -> HTTP {r.status_code} {'✅' if ok else '❌'}")
        if not ok:
            try:
                msg = r.json().get("error", {}).get("message", "")
                print(f"               {msg[:100]}")
            except Exception:
                pass
    except Exception as e:
        print(f"    {m:16s} -> ERROR {e}")
