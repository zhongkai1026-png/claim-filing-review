"""测试日期/金额格式统一函数。"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, ".")
from app.services.formatter import format_date_cn, format_amount, format_amount_text

print("=== 日期格式化（目标：2025年4月5日）===")
cases = ["2025-04-05", "2025/4/5", "2025.4.5", "2025年4月5日", "2025年04月05日",
         "2022年10月8号", "20250405", "2025-04-05 00:00:00", "2025-04-05T12:30:00",
         "", None, "不适用", "2024年9月2日"]
for c in cases:
    print(f"  {str(c)!r:<26} → {format_date_cn(c)!r}")

print("\n=== 金额格式化（目标：千分位）===")
for c in [2000000, 2000000.5, "2,000,000", "¥2,000,000元", "200万", 0, None,
          398348700, 60356051.2]:
    print(f"  {str(c)!r:<18} → 数值 {format_amount(c):<16} 文本 {format_amount_text(c)!r}")
