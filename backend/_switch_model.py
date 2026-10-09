"""把激活的 AI 配置模型切换为非思考模型（deepseek-chat）。

原模型 deepseek-flash 为思考型：思考过程与正文共用 max_tokens 额度，
在真实债权审查 prompt 下会把额度吃光导致正文为空/JSON 截断。

运行：python _switch_model.py [模型名]
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal  # noqa: E402
from app.models import AIConfig  # noqa: E402

target = sys.argv[1] if len(sys.argv) > 1 else "deepseek-chat"

db = SessionLocal()
try:
    cfg = db.query(AIConfig).filter(AIConfig.is_active == 1).first()
    if not cfg:
        sys.exit("没有激活的 AI 配置")
    old = cfg.model
    cfg.model = target
    if cfg.name and "GLM" not in cfg.name.upper():
        cfg.name = f"DeepSeek-{target}"
    db.commit()
    print(f"已切换：id={cfg.id} name={cfg.name!r} model={old!r} → {cfg.model!r} "
          f"base_url={cfg.base_url}")
finally:
    db.close()
