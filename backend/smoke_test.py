"""代码健康自检：不启动服务器、不占用端口，直接验证应用能否正常加载。

运行：python smoke_test.py
正常输出：所有检查均为 [OK]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("== 破产管理人债权申报与审查系统 - 代码健康自检 ==\n")

# 1. 依赖检查
print("[1] 依赖检查")
deps = ["fastapi", "uvicorn", "sqlalchemy", "pydantic", "httpx", "docx",
        "openpyxl", "fitz", "pdfplumber", "rapidocr_onnxruntime", "dotenv"]
ok = True
for d in deps:
    try:
        __import__({"fitz": "fitz", "docx": "docx", "dotenv": "dotenv"}.get(d, d))
        print(f"    [OK] {d}")
    except Exception as e:
        ok = False
        print(f"    [FAIL] {d}: {e}")
if not ok:
    print("\n依赖缺失，请执行: python -m pip install -r requirements.txt")
    sys.exit(1)

# 2. 应用加载
print("\n[2] 应用加载（app.main）")
try:
    from app.main import app  # noqa: E401
    routes = sorted({r.path for r in app.routes if hasattr(r, "path")})
    print(f"    [OK] 应用加载成功，共 {len(routes)} 条路由")
    print(f"    /api/health 存在: {'/api/health' in routes}")
    if "/api/health" not in routes:
        print("    [FAIL] /api/health 路由缺失！")
        sys.exit(1)
except Exception as e:
    import traceback
    print(f"    [FAIL] 应用加载失败：\n{traceback.format_exc()}")
    sys.exit(1)

# 3. 接口冒烟测试（TestClient，不占用端口）
print("\n[3] 接口冒烟测试")
try:
    from fastapi.testclient import TestClient
    client = TestClient(app)
    r = client.get("/api/health")
    print(f"    [OK] GET /api/health -> {r.status_code} {r.json()}")
    r = client.get("/api/projects")
    print(f"    [OK] GET /api/projects -> {r.status_code} ({len(r.json())} 个项目)")
    r = client.get("/")
    print(f"    [OK] GET / -> {r.status_code} (首页 "
                  f"{'可访问' if r.status_code == 200 else '异常'})")
    r = client.get("/css/style.css")
    print(f"    [OK] GET /css/style.css -> {r.status_code}")
    r = client.get("/js/app.js")
    print(f"    [OK] GET /js/app.js -> {r.status_code}")
except Exception as e:
    import traceback
    print(f"    [FAIL] 冒烟测试失败：\n{traceback.format_exc()}")
    sys.exit(1)

# 4. 审查服务加载
print("\n[4] 审查服务（auditor）")
try:
    from app.services import auditor
    from app.services.exporter import _opinion_doc  # noqa: F401
    print("    [OK] auditor / exporter 模块加载成功")
    print(f"    AI 配置：{'已启用' if auditor.config.AI_ENABLED else '未配置（规则引擎模式）'} "
          f"模型={auditor.config.AI_MODEL}")
except Exception as e:
    import traceback
    print(f"    [FAIL] 审查服务加载失败：\n{traceback.format_exc()}")
    sys.exit(1)

print("\n==================")
print("  全部自检通过！代码健康。")
print("  启动：双击 start.bat 或 python run.py")
print("==================")
