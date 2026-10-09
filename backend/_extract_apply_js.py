"""抽取申报页内联 JS 供 node --check 语法校验。"""
import pathlib
import re

ROOT = pathlib.Path(r"D:\Deepseek\培训-债权申报与审查")
out = ROOT / "backend" / "_apply_check.js"
srcs = [ROOT / "债权申报.html", ROOT / "cloud" / "receiver" / "static" / "index.html"]
blocks = []
for src in srcs:
    h = src.read_text(encoding="utf-8")
    m = re.findall(r"<script>(.*?)</script>", h, re.S)
    print(f"{src.name}: <script> 块 {len(m)} 个，最大 {max((len(x) for x in m), default=0)} 字符")
    blocks.append(m[-1])
# 两个文件内容应完全一致
print("两文件脚本一致：", blocks[0] == blocks[1])
out.write_text(blocks[0], encoding="utf-8")
print("已写出:", out)
