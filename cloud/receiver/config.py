# -*- coding: utf-8 -*-
"""债权申报接收服务配置（通过环境变量覆盖，生产环境由 /opt/claim-receiver/.env 提供）"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# 数据/暂存目录与静态页目录
DATA_DIR = Path(os.getenv("CLOUD_DATA_DIR", str(BASE_DIR / "data")))
STATIC_DIR = Path(os.getenv("CLOUD_STATIC_DIR", str(BASE_DIR / "static")))

# 监听端口（systemd 启动时使用）
PORT = int(os.getenv("CLOUD_PORT", "8080"))

# 管理员令牌：本地工具拉取时携带（Authorization: Bearer <token>）
ADMIN_TOKEN = os.getenv("CLOUD_ADMIN_TOKEN", "CHANGE-ME-TOKEN")

# 允许的项目码（多项目共用页面，逗号分隔）
PROJECT_CODES = {c.strip() for c in os.getenv("CLOUD_PROJECT_CODES", "DEMO2026").split(",") if c.strip()}

# 上传限制
ALLOWED_EXT = {
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt",
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp", ".zip",
}
MAX_FILE_MB = 50          # 单文件上限
MAX_FILES = 30            # 单次申报文件数上限
MAX_TOTAL_MB = 200        # 单次申报总大小上限

# 限流：单 IP 每小时最多提交次数（内存计数，单进程足够）
RATE_LIMIT = 10
RATE_WINDOW_SEC = 3600
