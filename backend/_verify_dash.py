"""验证 dashboard 统计接口（新口径：审查结论三组 + 性质构成）。

运行：python _verify_dash.py
"""
import json
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

r = urllib.request.urlopen("http://127.0.0.1:8000/api/projects/1/dashboard", timeout=10)
d = json.loads(r.read())

print("总笔数:", d["total"])
print("总览:", json.dumps(d["overview"], ensure_ascii=False))
print("\n申报债权性质构成:")
for x in d["nature_claimed"]:
    if x["count"]:
        print(f"  {x['name']}: {x['count']}笔 ¥{x['amount']:,.2f}")
print("\n审查结论三组:")
g = d.get("audit_groups", {})
for k in ("confirmed", "partial", "rejected"):
    x = g.get(k) or {}
    print(f"  {x.get('label')}: {x.get('count')}笔 ¥{x.get('amount'):,.2f}"
          f"（本金 {x.get('principal'):,.2f} / 利息 {x.get('interest'):,.2f} / 其他 {x.get('others'):,.2f}）")
    for n in (x.get("nature") or []):
        if n["count"]:
            print(f"      · {n['name']}: {n['count']}笔 ¥{n['amount']:,.2f}")
print(f"  尚未出结论: {g.get('no_conclusion')} 笔")
print("\n状态:", json.dumps(d["by_status"]))
print("AI 审查:", json.dumps(d["audit"], ensure_ascii=False))
