"""本地 OCR + 字段提取测试脚本：python ocr_test.py <文件路径>"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from app.services import extractor, parser  # noqa: E402

target = Path(sys.argv[1]) if len(sys.argv) > 1 else None
if not target or not target.exists():
    print("用法: python ocr_test.py <pdf或图片路径>")
    sys.exit(1)

t0 = time.time()
r = parser.parse_file(target, target.name)
print(f"文件: {target.name}")
print(f"耗时: {time.time() - t0:.1f}s")
print(f"状态: {r['parse_status']}")
print(f"文本长度: {len(r['text'])}")
print("--- 文本预览(前500字) ---")
print(r["text"][:500])

print("\n--- 字段提取 ---")
out = extractor._extract_by_rules(r["text"])
print(json.dumps({k: out[k] for k in [
    "name", "credit_code", "legal_rep", "contact_info", "address",
    "agent_name", "agent_contact", "bank_name", "account_no",
    "principal", "interest", "others", "claim_amount",
    "claim_date", "claim_nature", "claim_category", "litigation_status",
]}, ensure_ascii=False, indent=1))
