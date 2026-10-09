"""按选中导出（ids 参数）端到端验证：台账 Excel 与意见书 zip 只含选中债权。

运行：python _test_export_ids.py
"""
import io
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

BASE = "http://127.0.0.1:8000"
fails = []


def ok(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  → {extra}"))
    if not cond:
        fails.append(label)


def req(method, path, json_body=None, files=None):
    headers, body = {}, None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif files:
        b = "----expids"
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
        ctype = resp.headers.get("content-type", "")
        if "json" in ctype:
            return json.loads(raw.decode())
        return raw


print("== 准备数据：建临时项目 + 3 笔债权 ==")
for proj in req("GET", "/api/projects"):
    if proj["name"].startswith("导出选中测试"):
        for cl in req("GET", f"/api/claims?project_id={proj['id']}"):
            req("DELETE", f"/api/claims/{cl['id']}")
        req("DELETE", f"/api/projects/{proj['id']}")

pid = req("POST", "/api/projects", json_body={
    "name": "导出选中测试（自动清理）", "case_no": "TEST-EXP",
    "debtor": "测试债务人", "manager": "测试管理人"})["id"]
ids = []
for i, nm in enumerate(["导出甲", "导出乙", "导出丙"], start=1):
    c = req("POST", f"/api/projects/{pid}/upload",
            files=[(f"{nm}.txt", f"债权人：{nm}公司\n本金：{i}0000元\n".encode("utf-8"))])
    cid = c["id"]
    req("PUT", f"/api/claims/{cid}", json_body={"name": f"{nm}公司"})
    req("POST", f"/api/claims/{cid}/register")
    ids.append(cid)
time.sleep(8)
print(f"  项目 {pid}，债权 {ids}")

try:
    print("\n== 1. 台账 Excel ==")
    all_xlsx = req("GET", f"/api/export/ledger?project_id={pid}")
    ok(all_xlsx[:2] == b"PK" and len(all_xlsx) > 3000, "不带 ids：导出整个项目 xlsx", len(all_xlsx))
    part = req("GET", f"/api/export/ledger?project_id={pid}&ids={ids[0]}")
    ok(part[:2] == b"PK", "带 ids：导出成功（xlsx）", len(part))
    ok(len(part) < len(all_xlsx), "只导 1 笔比导全项目小", {"one": len(part), "all": len(all_xlsx)})

    def xlsx_rows(data):
        """用 openpyxl 读台账 xlsx 的「债权人名称」列（比对导出范围）。"""
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data))
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        hdr = None
        for i, r in enumerate(rows):
            cells = [str(c or "") for c in r]
            if "债权人名称" in cells:
                hdr = (i, cells.index("债权人名称"))
                break
        if not hdr:
            return []
        h, idx = hdr
        return [str(r[idx] or "") for r in rows[h + 1:] if r and r[idx]]
    names_all = xlsx_rows(all_xlsx)
    names_one = xlsx_rows(part)
    ok(len(names_all) == 3, "全量导出含 3 笔债权人", names_all)
    ok(names_one == ["导出甲公司"], "按 ids 导出只含选中的那 1 笔", names_one)
    two = req("GET", f"/api/export/ledger?project_id={pid}&ids={ids[0]},{ids[2]}")
    names_two = xlsx_rows(two)
    ok(names_two == ["导出甲公司", "导出丙公司"],
       "ids=两笔时只含这 2 笔，且按传入顺序排列", names_two)

    print("\n== 2. 意见书 zip ==")
    z_all = req("GET", f"/api/export/opinions?project_id={pid}")
    with zipfile.ZipFile(io.BytesIO(z_all)) as z:
        n_all = len([n for n in z.namelist() if n.endswith(".docx")])
    z_one = req("GET", f"/api/export/opinions?project_id={pid}&ids={ids[1]}")
    with zipfile.ZipFile(io.BytesIO(z_one)) as z:
        names = [n for n in z.namelist() if n.endswith(".docx")]
    ok(n_all == 3, "不带 ids：zip 含 3 份意见书", n_all)
    ok(len(names) == 1 and "PC-002" in names[0], "带 ids：zip 只含选中那 1 份（PC-002）", names)

    print("\n== 3. 异常参数 ==")
    try:
        req("GET", f"/api/export/ledger?project_id={pid}&ids=999999")
        ok(False, "ids 都不属于该项目时应报错")
    except urllib.error.HTTPError as e:
        ok(e.code == 400, "ids 无匹配时返回 400", e.code)
finally:
    print("\n== 清理 ==")
    req("POST", "/api/claims/batch-delete", json_body={"ids": ids})
    req("DELETE", f"/api/projects/{pid}")
    left = [x for x in req("GET", "/api/projects") if x["id"] == pid]
    ok(not left, "临时项目已删除")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 按选中导出全部通过")
