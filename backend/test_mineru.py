"""端到端测试：系统 parser 走 MinerU 通道解析图片/PDF。

用法：python test_mineru.py <file>
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app import config
from app.services import mineru, parser

print("=" * 56)
print("  系统 MinerU 通道端到端测试")
print("=" * 56)
print(f"  MINERU_API_KEY 配置: {'✅ 已配置' if mineru.is_configured() else '❌ 未配置'}")
print(f"  parser.mineru 已挂载: {hasattr(parser, 'mineru')}")

# 用一个真实文件测试（优先取上传目录里的第一个文件）
target = None
if len(sys.argv) > 1:
    p = Path(sys.argv[1])
    if p.exists():
        target = p
if not target:
    uploads = config.UPLOAD_DIR
    candidates = sorted(uploads.rglob("*")) if uploads.exists() else []
    for c in candidates:
        if c.is_file() and c.suffix.lower() in (".pdf", ".png", ".jpg", ".jpeg"):
            target = c
            break
if not target:
    print("\n❌ 未找到测试文件，请指定：python test_mineru.py <文件路径>")
    sys.exit(1)

print(f"\n测试文件: {target} ({target.stat().st_size} bytes)")

t0 = time.time()
result = parser.parse_file(target, target.name)
cost = round(time.time() - t0, 1)

print(f"解析状态: {result['parse_status']}")
print(f"解析耗时: {cost}s")
print(f"文本长度: {len(result['text'])}")
print(f"解析引擎: {result.get('engine') or '（无）'}")
if result["text"].strip():
    print("\n--- 解析文本预览（前 500 字）---")
    print(result["text"][:500])
else:
    print("\n⚠️ 未提取到文本（可能 MinerU 失败且本地 OCR 也无结果）")
