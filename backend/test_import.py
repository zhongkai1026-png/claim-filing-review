"""台账导出→导入 一致性测试：导出项目台账 Excel → 导入到临时项目 → 逐字段对比。

运行：python test_import.py
用途：验证「导出台账」与「导入台账」字段映射一致，导入后数据与源数据完全同步。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app import config  # noqa: E402
from app.database import SessionLocal, init_db  # noqa: E402
from app.models import Claim, Project  # noqa: E402
from app.services import exporter, importer  # noqa: E402

init_db()

# 对比字段（与导入映射一致）
COMPARE_FIELDS = [
    "name", "credit_code", "legal_rep", "contact_info", "address",
    "agent_name", "agent_id_no", "agent_contact", "agent_address",
    "account_name", "bank_name", "account_no",
    "claim_category", "litigation_status", "claim_nature", "claim_date",
    "principal", "interest", "others", "claim_amount",
    "audited_principal", "audited_interest", "audited_others", "audited_amount",
    "debt_nature", "guarantee_notes", "claim_type",
]
MONEY = {"principal", "interest", "others", "claim_amount",
         "audited_principal", "audited_interest", "audited_others",
         "audited_amount"}
STATUS_MAP = {"pending": "待登记", "registered": "已登记", "reviewed": "已复核"}


def norm(v):
    if v is None:
        return ""
    return str(v).strip()


def norm_money(v):
    try:
        return round(float(v or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def main():
    db = SessionLocal()
    try:
        # 1) 源数据：取当前所有项目的债权（或提供项目 id 参数）
        src_projects = db.query(Project).all()
        if not src_projects:
            print("❌ 系统无项目，无法测试")
            return
        for src in src_projects:
            src_claims = db.query(Claim).filter(
                Claim.project_id == src.id).all()
            if not src_claims:
                print(f"跳过项目「{src.name}」：无债权")
                continue
            print(f"\n== 测试项目「{src.name}」（{len(src_claims)} 笔债权）==")

            # 2) 导出 Excel
            xlsx = exporter.export_ledger(src, src_claims)
            print(f"导出 Excel：{len(xlsx)} 字节")

            # 3) 创建临时项目并导入
            tmp = Project(name="__import_test__")
            db.add(tmp)
            db.flush()
            result = importer.import_ledger_excel(xlsx, tmp.id, db)
            print(f"导入结果：{result.get('message', '')}")
            if result.get("errors"):
                print(f"  失败明细：{result['errors']}")
                db.rollback()
                db.delete(tmp)
                db.commit()
                return

            # 4) 逐字段对比
            imp_claims = db.query(Claim).filter(
                Claim.project_id == tmp.id).order_by(Claim.claim_no).all()
            mismatches = 0
            if len(imp_claims) != len(src_claims):
                print(f"❌ 债权数量不一致：源 {len(src_claims)} / 导入 {len(imp_claims)}")
                mismatches += 1
            for sc, ic in zip(src_claims, imp_claims):
                for f in COMPARE_FIELDS:
                    sv = getattr(sc, f)
                    iv = getattr(ic, f)
                    if f in MONEY:
                        ok = norm_money(sv) == norm_money(iv)
                    else:
                        ok = norm(sv) == norm(iv)
                    if not ok:
                        mismatches += 1
                        print(f"❌ 字段不一致 {sc.claim_no}.{f}: "
                              f"源={sv!r} 导入={iv!r}")
                # 状态映射
                if STATUS_MAP.get(sc.status, sc.status) != STATUS_MAP.get(
                        ic.status, ic.status):
                    mismatches += 1
                    print(f"❌ 状态不一致 {sc.claim_no}: "
                          f"源={sc.status} 导入={ic.status}")

            if mismatches == 0:
                print(f"✅ 项目「{src.name}」{len(src_claims)} 笔债权 "
                      f"全部字段一致（导出↔导入 round-trip 通过）")
            else:
                print(f"❌ 项目「{src.name}」存在 {mismatches} 处不一致")

            # 5) 清理临时项目
            db.delete(tmp)
            db.commit()

        print("\n==================")
        print("  测试完成。若存在 ❌ 不一致，请将输出发给管理员调整映射。")
        print("==================")
    finally:
        db.close()


if __name__ == "__main__":
    main()
