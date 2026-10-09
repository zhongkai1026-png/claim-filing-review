"""一次性修正历史解析状态（幂等）。

1. 无材料文件的债权（Excel 导入台账的行）→ parse_status='empty'（无材料无需解析）
2. 材料已全部解析完成、但债权级仍是 pending 的 → 'done'
3. 有材料且超过 30 分钟仍 parsing 的 → 'failed' 并写明原因（复用自愈逻辑）

运行：python _fix_parse_states.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal  # noqa: E402
from app.models import Claim  # noqa: E402
from app.routers.claims import heal_stale_parse  # noqa: E402

db = SessionLocal()
try:
    claims = db.query(Claim).all()
    n_empty = n_done = n_failed = 0
    for c in claims:
        st = c.parse_status or "pending"
        if st not in ("pending", "parsing"):
            continue
        if not c.files:
            c.parse_status = "empty"
            c.parse_error = ""
            c.parse_started_at = None
            n_empty += 1
            continue
        if st == "pending" and all((f.parse_status or "") in ("done", "empty")
                                   for f in c.files) and any((f.ocr_text or "").strip()
                                                             for f in c.files):
            c.parse_status = "done"
            c.parse_error = ""
            n_done += 1
            continue
        before = c.parse_status
        heal_stale_parse(db, c)
        if before != c.parse_status:
            n_failed += 1
    db.commit()
    print(f"  无材料 → empty：{n_empty} 笔")
    print(f"  材料已完成 → done：{n_done} 笔")
    print(f"  超时中断 → failed：{n_failed} 笔")
    print("\n  修正后各状态统计：")
    from sqlalchemy import func
    for st, n in db.query(Claim.parse_status, func.count(Claim.id)).group_by(
            Claim.parse_status).all():
        print(f"    {st or '(空)':<10} {n} 笔")
finally:
    db.close()
