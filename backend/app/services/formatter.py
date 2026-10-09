"""字段格式统一：日期 → 中文格式（2025年4月5日）；金额 → 数值（前端千分位显示）。

台账中所有日期类字段（申报债权时间等）统一在此归一，避免出现
2024-09-02 / 2024年09月02日 / 2022年10月8号 等混用格式。
"""
import re
from datetime import datetime

# 中文日期格式：2025年4月5日（不补前导零）
_DATE_CN = "{y}年{m}月{d}日"


def format_date_cn(v) -> str:
    """任意常见日期写法 → 「2025年4月5日」；无法识别时返回原值（去空白）。

    支持：2025-04-05 / 2025/4/5 / 2025.4.5 / 2025年4月5日 / 2025年04月05日
         2022年10月8号 / 20250405 / 2025-04-05 00:00:00 / Excel 日期序列值
    """
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""

    # 已是标准中文格式（含前导零或"号"）→ 重整为无前导零
    m = re.match(r"^(\d{4})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*[日号]?$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1900 <= y <= 2200 and 1 <= mo <= 12 and 1 <= d <= 31:
            return _DATE_CN.format(y=y, m=mo, d=d)

    # 纯 8 位数字：20250405
    m = re.match(r"^(\d{4})(\d{2})(\d{2})$", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1900 <= y <= 2200 and 1 <= mo <= 12 and 1 <= d <= 31:
            return _DATE_CN.format(y=y, m=mo, d=d)

    # 带时间的 ISO：2025-04-05 00:00:00 / 2025-04-05T00:00:00
    m = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[ T]", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1900 <= y <= 2200 and 1 <= mo <= 12 and 1 <= d <= 31:
            return _DATE_CN.format(y=y, m=mo, d=d)

    # 用标准解析器兜底（如 "April 5, 2025"、Excel 导出的 datetime）
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
                "%Y年%m月%d日", "%Y年%m月%d号"):
        try:
            dt = datetime.strptime(s, fmt)
            return _DATE_CN.format(y=dt.year, m=dt.month, d=dt.day)
        except ValueError:
            continue

    return s          # 无法识别：原样保留，避免丢信息


def format_amount(v) -> float:
    """金额 → 数值（去除千分位/币种符号/「万」单位），用于入库统一。"""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return round(float(v), 2)
    s = str(v).strip().replace(",", "").replace("，", "")
    s = re.sub(r"[¥￥元\s]", "", s)
    if not s:
        return 0.0
    if s.endswith("万"):
        try:
            return round(float(s[:-1]) * 10000, 2)
        except ValueError:
            return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def format_amount_text(v, keep_decimal: bool = False) -> str:
    """金额 → 千分位文本（金额格式统一：2000000 → 2,000,000）。

    支持字符串输入（含千分位、币种符号、「万」单位）。
    keep_decimal=False 时整数省略小数位（2,000,000），有小数则保留 2 位（2,000,000.50）。
    """
    n = format_amount(v)
    if keep_decimal or abs(n - round(n)) > 0.001:
        return f"{n:,.2f}"
    return f"{int(round(n)):,}"
