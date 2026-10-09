"""迁移：重建 claims 表，去掉 claim_no 的全表 UNIQUE 约束（改为项目内唯一）。"""
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import config  # noqa: E402
from app.database import engine  # noqa: E402

DB = config.DB_PATH
if not DB.exists():
    print("数据库不存在，无需迁移")
    sys.exit(0)

# 备份
bak = DB.with_suffix(".db.bak")
shutil.copy2(DB, bak)
print(f"已备份到 {bak}")

from sqlalchemy import text  # noqa: E402

with engine.begin() as conn:
    # 旧表结构（去掉 claim_no UNIQUE）
    conn.execute(text("PRAGMA foreign_keys=OFF"))
    conn.execute(text("ALTER TABLE claims RENAME TO claims_old"))
    conn.execute(text("""
        CREATE TABLE claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            claim_no VARCHAR(50),
            name VARCHAR(200) DEFAULT '',
            credit_code VARCHAR(100) DEFAULT '',
            legal_rep VARCHAR(100) DEFAULT '',
            contact_info VARCHAR(200) DEFAULT '',
            address VARCHAR(300) DEFAULT '',
            agent_name VARCHAR(100) DEFAULT '',
            agent_id_no VARCHAR(100) DEFAULT '',
            agent_contact VARCHAR(200) DEFAULT '',
            agent_address VARCHAR(300) DEFAULT '',
            account_name VARCHAR(100) DEFAULT '',
            bank_name VARCHAR(100) DEFAULT '',
            account_no VARCHAR(100) DEFAULT '',
            claim_category VARCHAR(50) DEFAULT '',
            litigation_status VARCHAR(20) DEFAULT '',
            claim_nature VARCHAR(50) DEFAULT '',
            claim_date VARCHAR(50) DEFAULT '',
            principal NUMERIC(15,2) DEFAULT 0,
            interest NUMERIC(15,2) DEFAULT 0,
            others NUMERIC(15,2) DEFAULT 0,
            claim_amount NUMERIC(15,2) DEFAULT 0,
            audited_principal NUMERIC(15,2) DEFAULT 0,
            audited_interest NUMERIC(15,2) DEFAULT 0,
            audited_others NUMERIC(15,2) DEFAULT 0,
            audited_amount NUMERIC(15,2) DEFAULT 0,
            debt_nature VARCHAR(50) DEFAULT '',
            guarantee_notes TEXT DEFAULT '',
            claim_type VARCHAR(50) DEFAULT '',
            source_files TEXT DEFAULT '',
            status VARCHAR(20) DEFAULT 'pending',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))
    conn.execute(text("""
        INSERT INTO claims SELECT * FROM claims_old
    """))
    conn.execute(text("DROP TABLE claims_old"))
    conn.execute(text("CREATE INDEX ix_claims_project_id ON claims (project_id)"))
    conn.execute(text("CREATE INDEX ix_claims_claim_no ON claims (claim_no)"))
    conn.execute(text("PRAGMA foreign_keys=ON"))

print("迁移完成：claim_no 已改为项目内唯一")
