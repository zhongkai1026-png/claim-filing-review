"""查看台账中日期与金额字段的实际格式。"""
import sqlite3
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from app import config

con = sqlite3.connect(str(config.DB_PATH))
con.row_factory = sqlite3.Row

print("=== claim_date 现有格式 ===")
for r in con.execute("SELECT claim_no, name, claim_date FROM claims "
                     "WHERE project_id=1 ORDER BY id LIMIT 30"):
    print(f"  {r['claim_no']:<8} {(r['name'] or '')[:16]:<18} date={r['claim_date']!r}")

print("\n=== 金额字段（数据库中为数值）===")
for r in con.execute("SELECT claim_no, principal, claim_amount FROM claims "
                     "WHERE project_id=1 ORDER BY claim_amount DESC LIMIT 5"):
    print(f"  {r['claim_no']:<8} principal={r['principal']!r} amount={r['claim_amount']!r}")

print("\n=== online_claims 的 claim_date ===")
for r in con.execute("SELECT submit_no, name, claim_date FROM online_claims LIMIT 8"):
    print(f"  {r['submit_no']:<8} {(r['name'] or '')[:14]:<16} date={r['claim_date']!r}")
con.close()
