"""CSS 体检：括号配平、可疑合并行、关键布局规则是否在位。"""
import re
from pathlib import Path

p = Path(r"D:\Deepseek\培训-债权申报与审查\backend\static\css\style.css")
css = p.read_text(encoding="utf-8")

print(f"文件行数 {css.count(chr(10)) + 1}，字符数 {len(css)}")
print(f"花括号配平：{css.count('{')} 开 / {css.count('}')} 闭 →",
      "✅ 配平" if css.count("{") == css.count("}") else "❌ 不配平")

print("\n== 可疑合并行（一行里出现两个规则块）==")
bad = 0
for i, line in enumerate(css.splitlines(), 1):
    if line.count("{") > 1 or (line.count("}") >= 1 and "{" in line and line.strip().index("}") > 0):
        # 同一行既有 } 又有 { → 可能是两行被合并
        if re.search(r"\}\s*[.#a-zA-Z].*\{", line):
            print(f"  行 {i}: {line[:110]}")
            bad += 1
print(f"  可疑行数：{bad}")

print("\n== 关键布局规则是否在位 ==")
keys = [".dash-cols", ".grid-2", ".stats", ".action-cards", ".quick-actions",
        ".view-tabs", ".batch-bar", ".chips", ".warn-bar", ".dash-group",
        ".row-menu-pop", ".tbl th.col-actions", ".ledger-scroll", ".tbl .num"]
for k in keys:
    idx = css.find(k)
    if idx == -1:
        print(f"  ❌ 缺失 {k}")
        continue
    seg = css[idx:idx + 220].split("\n")[0]
    print(f"  ✅ {k}  → {seg.strip()[:100]}")

print("\n== 最近改动区域的规则（人工看看有没有串行）==")
for anchor in [".warn-bar", ".chips {" , ".dash-group", ".table-tip"]:
    idx = css.find(anchor)
    if idx != -1:
        print("  --- " + anchor + " ---")
        print("  " + css[idx:idx + 260].replace("\n", "\n  "))
