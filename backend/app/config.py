"""应用配置：从 .env 读取，未配置时使用默认值（本地零配置可跑）。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent  # backend/
load_dotenv(BASE_DIR / ".env")

DATA_DIR = Path(os.getenv("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "claims.db"
EXPORT_DIR = DATA_DIR / "exports"

# AI 审查（OpenAI 兼容接口，默认 DeepSeek）
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
AI_API_KEY = os.getenv("AI_API_KEY", "")
AI_MODEL = os.getenv("AI_MODEL", "deepseek-chat")
AI_TIMEOUT = int(os.getenv("AI_TIMEOUT", "180"))
# 单次生成 token 上限。注意：思考型模型（reasoning）的思考过程与正文共用该额度，
# 额度偏小会出现「思考吃满 → 正文为空 / JSON 被截断」，故默认给足。
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", "12000"))
# 审查提示词档位：full=通用规则20条+类型化标准11类（默认）；
# basic=精简版（核心7条规则、不注入类型化标准），用于出问题时快速回退/省 token
AI_PROMPT_PROFILE = os.getenv("AI_PROMPT_PROFILE", "full")
AI_ENABLED = bool(AI_API_KEY)

# MinerU 云端文档解析（扫描件/图片 OCR、表格/公式还原；未配置时回退本地 RapidOCR）
MINERU_API_KEY = os.getenv("MINERU_API_KEY", "")
MINERU_TIMEOUT = int(os.getenv("MINERU_TIMEOUT", "120"))
MINERU_POLL_SEC = int(os.getenv("MINERU_POLL_SEC", "4"))
MINERU_POLL_MAX = int(os.getenv("MINERU_POLL_MAX", "120"))

# 管理员（可选，本地工具默认不鉴权）
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

for d in (DATA_DIR, UPLOAD_DIR, EXPORT_DIR):
    d.mkdir(parents=True, exist_ok=True)
