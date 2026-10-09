"""一键添加并激活 AI 债权审查模型配置。

用法：python add_ai_config.py
自动完成：探测接口地址（原地址 / 加 /v1）→ 测试连通 → 写入数据库并激活。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

KEY = "sk-JeM7UsOsdTYODMij4glo1IlwqlKUshWSOk8sSuciEbDHwmUW"
URL = "https://newapi.web.azshentong.com"
MODEL = "GLM-5.2"
NAME = "GLM-5.2"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def probe(base_url: str, model: str) -> tuple:
    """测试一个 base_url + model 组合，返回 (ok, detail)。"""
    import httpx
    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {KEY}"},
            json={"model": model,
                  "messages": [{"role": "user", "content": "hi"}],
                  "max_tokens": 5},
            timeout=30,
        )
        if r.status_code == 200:
            return True, "OK"
        detail = ""
        try:
            detail = r.json().get("error", {}).get("message", "")
        except Exception:
            pass
        return False, f"HTTP {r.status_code} {detail or r.text[:120]}"
    except Exception as e:
        return False, str(e)


def main():
    from app.database import SessionLocal, init_db
    from app.models import AIConfig

    print("=" * 56)
    print("  添加 AI 模型配置：GLM-5.2")
    print("=" * 56)

    # ---- 1. 探测 base_url ----
    candidates = [URL, URL + "/v1"]
    model_candidates = [MODEL, MODEL.lower(), "glm-4.5"]
    ok_url, ok_model = None, None
    print("\n[1] 探测接口地址与模型名")
    for base in candidates:
        for m in model_candidates:
            ok, detail = probe(base, m)
            print(f"    {base} / {m}  ->  {'✅ ' + detail if ok else '❌ ' + detail}")
            if ok:
                ok_url, ok_model = base, m
                break
        if ok_url:
            break

    if not ok_url:
        print("\n❌ 所有组合均连接失败，请检查：")
        print("   1) 网络能否访问该网址")
        print("   2) Key 是否有效")
        print("   3) 服务端是否需要 /v1 或其他路径")
        sys.exit(1)

    print(f"\n   探测成功：{ok_url} / {ok_model}")

    # ---- 2. 写入数据库并激活 ----
    print("\n[2] 写入数据库并激活")
    init_db()
    db = SessionLocal()
    try:
        # 同名配置则更新，否则新建
        cfg = db.query(AIConfig).filter(AIConfig.name == NAME).first()
        if not cfg:
            cfg = AIConfig(name=NAME)
            db.add(cfg)
        cfg.base_url = ok_url
        cfg.api_key = KEY
        cfg.model = ok_model
        # 激活新配置
        db.query(AIConfig).update({AIConfig.is_active: 0})
        cfg.is_active = 1
        db.commit()
        db.refresh(cfg)
        print(f"    ✅ 已保存并激活：")
        print(f"        名称     : {cfg.name}")
        print(f"        接口地址 : {cfg.base_url}")
        print(f"        模型名   : {cfg.model}")
        print(f"        激活状态 : {'是' if cfg.is_active else '否'}")
    finally:
        db.close()

    print("\n" + "=" * 56)
    print("  完成！重启后端后生效（restart.bat）")
    print("  验证：http://127.0.0.1:8000/api/health")
    print("  应显示 ai_config = GLM-5.2")
    print("=" * 56)


if __name__ == "__main__":
    main()
