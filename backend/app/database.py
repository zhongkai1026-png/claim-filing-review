"""SQLAlchemy 引擎与会话。"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_conn, _record):
    """SQLite WAL + busy_timeout：让异步解析/导入等并发读写互不阻塞。"""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=30000")
    finally:
        cur.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  确保模型已注册

    Base.metadata.create_all(bind=engine)
    ensure_columns()


def ensure_columns():
    """幂等补列：老库自动补齐新增字段（SQLite ALTER TABLE）。"""
    from sqlalchemy import text
    with engine.begin() as conn:
        cols = [r[1] for r in conn.execute(
            text("PRAGMA table_info(claims)")).fetchall()]
        if "parse_status" not in cols:
            conn.execute(text(
                "ALTER TABLE claims ADD COLUMN parse_status "
                "VARCHAR(20) DEFAULT 'pending'"))
            print("[db] claims 表已补充 parse_status 列")
        # claims.parse_started_at / parse_error：解析卡死识别与失败原因（老库补列）
        if "parse_started_at" not in cols:
            conn.execute(text(
                "ALTER TABLE claims ADD COLUMN parse_started_at DATETIME"))
            print("[db] claims 表已补充 parse_started_at 列")
        if "parse_error" not in cols:
            conn.execute(text(
                "ALTER TABLE claims ADD COLUMN parse_error VARCHAR(300) DEFAULT ''"))
            print("[db] claims 表已补充 parse_error 列")
        # claims.verified_at：人工初审/编辑或复核确认时间（AI 审查据此判断数据优先级）
        if "verified_at" not in cols:
            conn.execute(text(
                "ALTER TABLE claims ADD COLUMN verified_at DATETIME"))
            print("[db] claims 表已补充 verified_at 列")
        cols2 = [r[1] for r in conn.execute(
            text("PRAGMA table_info(online_claims)")).fetchall()]
        if "cloud_claim_id" not in cols2:
            conn.execute(text(
                "ALTER TABLE online_claims ADD COLUMN "
                "cloud_claim_id VARCHAR(100) DEFAULT ''"))
            conn.execute(text(
                "ALTER TABLE online_claims ADD COLUMN cloud_pulled_at DATETIME"))
            print("[db] online_claims 表已补充 cloud 拉取列")
        # projects.cloud_code：云端项目码（老库补列）
        cols3 = [r[1] for r in conn.execute(
            text("PRAGMA table_info(projects)")).fetchall()]
        if "cloud_code" not in cols3:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN cloud_code "
                "VARCHAR(100) DEFAULT ''"))
            print("[db] projects 表已补充 cloud_code 列")
        # projects.accept_date：破产受理日期（老库补列）
        if "accept_date" not in cols3:
            conn.execute(text(
                "ALTER TABLE projects ADD COLUMN accept_date "
                "VARCHAR(30) DEFAULT ''"))
            print("[db] projects 表已补充 accept_date 列")
        # claim_files.parse_engine：解析引擎标记（老库补列）
        cols4 = [r[1] for r in conn.execute(
            text("PRAGMA table_info(claim_files)")).fetchall()]
        if "parse_engine" not in cols4:
            conn.execute(text(
                "ALTER TABLE claim_files ADD COLUMN parse_engine "
                "VARCHAR(20) DEFAULT ''"))
            print("[db] claim_files 表已补充 parse_engine 列")
        # audit_results.opinion_draft：意见书编辑稿（老库补列）
        cols5 = [r[1] for r in conn.execute(
            text("PRAGMA table_info(audit_results)")).fetchall()]
        if "opinion_draft" not in cols5:
            conn.execute(text(
                "ALTER TABLE audit_results ADD COLUMN opinion_draft TEXT "
                "DEFAULT ''"))
            print("[db] audit_results 表已补充 opinion_draft 列")
        if "ai_started_at" not in cols5:
            conn.execute(text(
                "ALTER TABLE audit_results ADD COLUMN ai_started_at DATETIME"))
            print("[db] audit_results 表已补充 ai_started_at 列")
        # audit_results.prompt_version / injected_standards：审查提示词版本与注入标准（老库补列）
        if "prompt_version" not in cols5:
            conn.execute(text(
                "ALTER TABLE audit_results ADD COLUMN prompt_version "
                "VARCHAR(30) DEFAULT ''"))
            print("[db] audit_results 表已补充 prompt_version 列")
        if "injected_standards" not in cols5:
            conn.execute(text(
                "ALTER TABLE audit_results ADD COLUMN injected_standards "
                "VARCHAR(200) DEFAULT ''"))
            print("[db] audit_results 表已补充 injected_standards 列")
        # audit_results.injected_case_info：本次注入的案件信息（含破产受理日）
        if "injected_case_info" not in cols5:
            conn.execute(text(
                "ALTER TABLE audit_results ADD COLUMN injected_case_info "
                "VARCHAR(500) DEFAULT ''"))
            print("[db] audit_results 表已补充 injected_case_info 列")
        # claim_files.origin：材料来源（补充材料标记，老库补列）
        if "origin" not in cols4:
            conn.execute(text(
                "ALTER TABLE claim_files ADD COLUMN origin "
                "VARCHAR(20) DEFAULT ''"))
            print("[db] claim_files 表已补充 origin 列")
