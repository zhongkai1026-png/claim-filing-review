"""历史数据格式统一：把已有台账与在线申报的日期字段统一为「2025年4月5日」。

先备份数据库，再执行；仅修改格式不一致的记录。
"""
import shutil
import sqlite3
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from app import config
from app.services.formatter import format_date_cn

db = config.DB_PATH
bak = f"{db}.bak_fmt_{datetime.now():%Y%m%d_%H%M%S}"
shutil.copy2(db, bak)
print(f"已备份数据库: {bak}\n")

con = sqlite3.connect(str(db))
con.row_factory = sqlite3.Row


def migrate(table: str, date_col: str = "claim_date"):
    rows = con.execute(f"SELECT id, {date_col} AS d FROM {table} "
                       f"WHERE {date_col} IS NOT NULL AND {date_col} != ''").fetchall()
    changed = 0
    samples = []
    for r in rows:
        old = r["d"]
        new = format_date_cn(old)
        if new and new != old:
            con.execute(f"UPDATE {table} SET {date_col}=? WHERE id=?", (new, r["id"]))
            changed += 1
            if len(samples) < 8:
                samples.append((old, new))
    print(f"[{table}] 检查 {len(rows)} 条，修改 {changed} 条")
    for old, new in samples:
        print(f"    {old!r} → {new!r}")
    return changed


total = migrate("claims")
total += migrate("online_claims")
con.commit()
con.close()
print(f"\n合计修改 {total} 条日期记录")

# 验证
con = sqlite3.connect(str(db))
print("\n=== 迁移后日期样例 ===")
for r in con.execute("SELECT claim_no, claim_date FROM claims "
                     "WHERE claim_date != '' ORDER BY id LIMIT 12"):
    print(f"  {r[0]:<8} {r[1]}")
con.close()
