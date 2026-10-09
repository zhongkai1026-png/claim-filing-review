"""验证：台账日期格式 + 导出 Excel 金额千分位格式。"""
import io
import json
import sys
import urllib.request
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE = "http://127.0.0.1:8000"

# 1. 台账日期
claims = json.loads(urllib.request.urlopen(
    f"{BASE}/api/claims?project_id=1", timeout=10).read())
print("=== 台账日期格式（应全部为 X年X月X日）===")
bad = 0
for c in claims[:10]:
    d = c.get("claim_date") or ""
    ok = (not d) or ("年" in d and "月" in d and "日" in d and "-" not in d)
    if not ok:
        bad += 1
    print(f"  {c['claim_no']:<8} {d or '(空)':<16} {'✅' if ok else '❌'}")
print(f"  格式异常: {bad} 条")

# 2. 导出 Excel 检查金额格式
print("\n=== 导出台账 Excel 检查 ===")
r = urllib.request.urlopen(f"{BASE}/api/export/ledger?project_id=1", timeout=30)
data = r.read()
print(f"  文件大小: {len(data)} 字节")
z = zipfile.ZipFile(io.BytesIO(data))
sheet = z.read("xl/worksheets/sheet1.xml").decode("utf-8", "ignore")
styles = z.read("xl/styles.xml").decode("utf-8", "ignore")
has_fmt = "#,##0.##" in styles
print(f"  千分位数字格式已定义: {'✅' if has_fmt else '❌'}")
print(f"  含金额数值（非文本）: {'✅' if '<v>200000000</v>' in sheet or '<v>398348700</v>' in sheet else '可能为文本'}")
