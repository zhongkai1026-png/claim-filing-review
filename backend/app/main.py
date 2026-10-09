"""FastAPI 应用入口：API + 静态前端。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .database import init_db
from .routers import (
    ai_configs, audit, claims, cloud_sync, dashboard, export, files, imports,
    online_claims, projects,
)
from .services import llm

app = FastAPI(title="破产管理人债权申报与审查系统", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def utf8_json_charset(request, call_next):
    """JSON 响应显式标注 UTF-8，兼容老版客户端（如 PowerShell 5.1）。"""
    response = await call_next(request)
    ct = response.headers.get("content-type", "")
    if ct.startswith("application/json") and "charset" not in ct:
        response.headers["content-type"] = "application/json; charset=utf-8"
    return response

app.include_router(projects.router)
app.include_router(claims.router)
app.include_router(files.router)
app.include_router(audit.router)
app.include_router(export.router)
app.include_router(imports.router)
app.include_router(online_claims.router)
app.include_router(ai_configs.router)
app.include_router(cloud_sync.router)
app.include_router(dashboard.router)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    cfg = llm.get_active_config()
    return {
        "ok": True,
        "version": "2.0-methodology",
        "ai_enabled": bool(cfg),
        "ai_model": (cfg or {}).get("model", ""),
        "ai_config": (cfg or {}).get("name", ""),
        "data_dir": str(config.DATA_DIR),
    }


# 静态前端（最后一个挂载，兜底路由）
STATIC_DIR = config.BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True),
              name="static")
