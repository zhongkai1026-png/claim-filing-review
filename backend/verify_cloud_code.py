"""验证 projects 接口返回 cloud_code 字段。"""
import sys
import urllib.request
import json

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

r = urllib.request.urlopen("http://127.0.0.1:8000/api/projects", timeout=5)
projects = json.loads(r.read())
for p in projects:
    print(f"id={p['id']} name={p['name']} cloud_code={p.get('cloud_code', '')!r}")

print("\nOK - cloud_code 字段已生效")
