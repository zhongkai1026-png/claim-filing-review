"""历史数据回填 + 验证：人工确认标记（claims.verified_at）。

AI 审查的「数据优先级规则」依赖 verified_at 判断台账数据是否为人工确认口径：
- 已完成人工复核（audit_results.manual_status='done'）的历史债权 → 用复核时间回填；
- 状态为「已复核」但无复核时间的 → 用 updated_at 回填；
- 其余（仅上传或仅批量登记、无人工编辑证据的）保持为空，AI 审查将按"系统解析预填"处理。

运行：python _backfill_verified.py          # 预览
      python _backfill_verified.py --apply  # 实际写入
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.database import SessionLocal  # noqa: E402
from app.models import AuditResult, Claim  # noqa: E402

apply = "--apply" in sys.argv
db = SessionLocal()
try:
    audits = {a.claim_id: a for a in db.query(AuditResult).all()}
    plan = []
    for c in db.query(Claim).all():
        if c.verified_at:
            continue
        a = audits.get(c.id)
        if a and a.manual_status == "done":
            plan.append((c, a.audited_at or c.updated_at or c.created_at, "人工复核已完成"))
        elif (c.status or "") == "reviewed":
            plan.append((c, c.updated_at or c.created_at, "状态=已复核"))
    print(f"待回填 {len(plan)} 笔：")
    for c, ts, why in plan:
        print(f"  {c.claim_no:<8} {str(c.name)[:16]:<18} {why:<12} → {str(ts)[:16]}")
        if apply:
            c.verified_at = ts
    if apply:
        db.commit()
        print("已写入")
    else:
        print("\n（未写入；加 --apply 执行）")
    total = db.query(Claim).count()
    marked = db.query(Claim).filter(Claim.verified_at.isnot(None)).count()
    print(f"\n当前台账确认口径：{marked}/{total} 笔标记为「已人工确认」")
finally:
    db.close()
