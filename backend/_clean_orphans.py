"""清理历史孤儿行（父记录已删除的子表行）。

背景：旧版删除逻辑用 bulk delete 与会话中已加载对象冲突（SAWarning），
在删除债权时可能残留 claim_files / audit_results 孤儿行。

运行：python _clean_orphans.py          # 仅统计
      python _clean_orphans.py --apply  # 实际清理
"""
import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).parent / "data" / "claims.db"
apply = "--apply" in sys.argv

conn = sqlite3.connect(DB)
try:
    for table, col, parent in (("claim_files", "claim_id", "claims"),
                               ("audit_results", "claim_id", "claims"),
                               ("online_claim_files", "online_claim_id", "online_claims")):
        rows = conn.execute(
            f"SELECT count(*) FROM {table} WHERE {col} NOT IN (SELECT id FROM {parent})"
        ).fetchone()[0]
        print(f"{table}: 孤儿行 {rows}")
        if rows and apply:
            conn.execute(
                f"DELETE FROM {table} WHERE {col} NOT IN (SELECT id FROM {parent})")
    if apply:
        conn.commit()
        print("已清理并提交")
    else:
        print("\n（未做修改；加 --apply 执行清理）")
finally:
    conn.close()
