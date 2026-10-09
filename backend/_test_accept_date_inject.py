"""离线验证：案件信息注入（含破产受理日）+ 解析卡死自愈 + 日期年份校正。

不动服务，直接调用服务层函数与数据库。
运行：python _test_accept_date_inject.py
"""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services import auditor as A  # noqa: E402
from app.services import extractor as E  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Claim, Project  # noqa: E402
from app.routers.claims import heal_stale_parse, PARSE_TIMEOUT_MIN  # noqa: E402

fails = []


def ok(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  → {extra}"))
    if not cond:
        fails.append(label)


print("== 1. 案件信息块（含破产受理日） ==")
db = SessionLocal()
p2 = db.get(Project, 2)
info = A.build_case_info(p2)
print("  " + info.replace("\n", "\n  "))
ok("破产受理日" in info, "案件信息包含破产受理日字段")
ok("未填写" in info and "无法判断" in info,
   "受理日为空时明确要求“无法判断/需补充”，并禁止臆造日期")

p_full = Project(name="测试", case_no="（2024）川1922破1号", debtor="某某公司",
                 manager="某某律所", accept_date="2024-11-18")
info2 = A.build_case_info(p_full)
ok("2024-11-18" in info2, "受理日已填时原样注入", info2.replace("\n", " / "))
ok("无法判断" not in info2, "受理日已填时不再提示缺失")

print("\n== 2. 审查提示词确实带上案件信息与基准日纪律 ==")
user_msg = (A.AUDIT_USER
            .replace("{TYPE_STANDARD}", "【测试标准】")
            .replace("{CASE_INFO}", info2)
            .replace("{claim_json}", "{}")
            .replace("{text_preview}", "（无）"))
ok("{CASE_INFO}" not in user_msg, "占位符已被替换")
ok("案件信息" in user_msg and "2024-11-18" in user_msg, "user 提示词含案件信息与受理日")
ok("基准日" in A.AUDIT_SYSTEM and "不得把材料中的年份改写成当前年份" in A.AUDIT_SYSTEM,
   "system 提示词写明期间判断基准与日期纪律")

print("\n== 3. 日期年份校正（材料原文优先） ==")
cases = [
    ("申报时间2020年8月18日", "2026年8月18日", "2020年8月18日"),
    ("申报时间2024年11月18日", "2026年11月18日", "2024年11月18日"),
    ("无任何日期", "2026年8月18日", "2026年8月18日"),
]
for text, val, want in cases:
    got = E._date_year_from_text(text, val)
    ok(got == want, f"「{text}」+ 提取值 {val} → {got}", f"期望 {want}")

print("\n== 4. 解析卡死自愈 ==")
c = db.get(Claim, 120)
print(f"  张军(120) 当前 parse_status={c.parse_status!r} started={c.parse_started_at} error={c.parse_error!r}")
old = (c.parse_status, c.parse_started_at, c.parse_error)
try:
    c.parse_status = "parsing"
    c.parse_started_at = datetime.now() - timedelta(minutes=PARSE_TIMEOUT_MIN + 5)
    db.commit()
    c2 = heal_stale_parse(db, db.get(Claim, 120))
    ok(c2.parse_status == "failed", "超时未完成的解析被标记为 failed", c2.parse_status)
    ok("重新解析" in (c2.parse_error or ""), "并写明原因", c2.parse_error)
finally:
    # 保持 failed 状态（用户可直接重新解析），但清空计时起点
    c3 = db.get(Claim, 120)
    if c3.parse_status == "parsing":
        c3.parse_status, c3.parse_started_at, c3.parse_error = old
    else:
        c3.parse_started_at = None
    for f in c3.files:
        if f.parse_status in ("pending", "parsing"):
            f.parse_status = "failed"
    db.commit()
    print(f"  已解开卡死状态 → parse_status={c3.parse_status!r} error={(c3.parse_error or '')[:60]!r}")
    ok(c3.parse_status == "failed", "张军这笔现在可重新解析（不再是 parsing）", c3.parse_status)

db.close()

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 全部通过")
