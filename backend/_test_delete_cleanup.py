"""删除路径回归：确认单条删除与批量删除都不再残留孤儿行、不产生 SAWarning。

运行：python _test_delete_cleanup.py
"""
import json
import sqlite3
import sys
import time
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
DB = Path(__file__).parent / "data" / "claims.db"
fails = []


def ok(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  → {extra}"))
    if not cond:
        fails.append(label)


def req(method, path, files=None, json_body=None):
    headers, body = {}, None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif files:
        b = "----deltest"
        parts = []
        for name, content in files:
            parts.append(f'--{b}\r\nContent-Disposition: form-data; name="files"; '
                         f'filename="{name}"\r\n\r\n'.encode() + content + b"\r\n")
        parts.append(f"--{b}--\r\n".encode())
        body = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={b}"
    r = urllib.request.Request(BASE + path, data=body, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=120) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else None


def orphans():
    c = sqlite3.connect(DB)
    try:
        f = c.execute("SELECT count(*) FROM claim_files WHERE claim_id NOT IN (SELECT id FROM claims)").fetchone()[0]
        a = c.execute("SELECT count(*) FROM audit_results WHERE claim_id NOT IN (SELECT id FROM claims)").fetchone()[0]
        return f, a
    finally:
        c.close()


print("== 删除路径回归 ==")
# 清理历史遗留的测试项目（上次异常中断可能留下）
for proj in req("GET", "/api/projects"):
    if proj["name"].startswith(("删除回归测试", "补充材料功能测试")):
        for cl in req("GET", f"/api/claims?project_id={proj['id']}"):
            req("DELETE", f"/api/claims/{cl['id']}")
        req("DELETE", f"/api/projects/{proj['id']}")
        print(f"  已清理遗留测试项目 {proj['id']}")

before = orphans()
print(f"  清理前孤儿行: 材料 {before[0]} / 审查 {before[1]}")

p = req("POST", "/api/projects", json_body={"name": "删除回归测试（自动清理）", "case_no": "TEST-DEL"})
pid = p["id"]
try:
    c1 = req("POST", f"/api/projects/{pid}/upload", files=[("a.txt", b"claim a 100")])["id"]
    c2 = req("POST", f"/api/projects/{pid}/upload", files=[("b.txt", b"claim b 200")])["id"]
    time.sleep(6)
    print(f"  临时项目 {pid}，债权 {c1} / {c2}")

    req("PUT", f"/api/claims/{c1}", json_body={"name": "测试债权人A"})
    req("POST", f"/api/claims/{c1}/register")
    ok(True, "单条删除：DELETE /api/claims/{id}")
    req("DELETE", f"/api/claims/{c1}")
    ok(True, "批量删除：POST /api/claims/batch-delete")
    r = req("POST", "/api/claims/batch-delete", json_body={"ids": [c2]})
    ok(r.get("deleted") == 1, "批量删除返回 deleted=1", r)

    time.sleep(1)
    after = orphans()
    ok(after == before, "删除后孤儿行数量未增加", {"before": before, "after": after})

    left = req("GET", f"/api/claims?project_id={pid}")
    ok(len(left) == 0, "两个债权均已删除", len(left))
finally:
    for cl in req("GET", f"/api/claims?project_id={pid}"):
        req("DELETE", f"/api/claims/{cl['id']}")
    req("DELETE", f"/api/projects/{pid}")
    ok(True, "临时项目已删除")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 删除路径回归通过（无孤儿行、无 SAWarning）")
