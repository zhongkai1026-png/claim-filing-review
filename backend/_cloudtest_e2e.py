"""云端接收服务 + 新版申报页端到端联调（本地 8099 端口）。

验证：新证据目录页由接收服务托管 → 按「证据名称-原文件名」提交 → manifest 正确落盘 → 管理端拉取列表可见。
运行：python _cloudtest_e2e.py
"""
import io
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

BASE = "http://127.0.0.1:8099"
DATA = Path(r"D:\Deepseek\培训-债权申报与审查\backend\_cloudtest\data\cloud")

fails = []


def ok(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  → {extra}"))
    if not cond:
        fails.append(label)


def post_apply(files):
    boundary = "----test" + uuid.uuid4().hex
    parts = []

    def field(name, value):
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())

    field("project", "TEST2026")
    field("name", "重庆测试建材有限公司")
    field("credit_code", "91500000TEST0001XY")
    field("contact", "13800000000")
    field("claim_category", "购销")
    field("claim_nature", "普通债权")
    field("claim_amount", "856000")
    field("remark", "联调测试")
    for fname, content in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{fname}"\r\n'
            f'Content-Type: application/octet-stream\r\n\r\n'.encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    body = b"".join(parts)
    req = urllib.request.Request(BASE + "/api/apply", data=body, method="POST",
                                headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def get(path, token=None):
    req = urllib.request.Request(BASE + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read()


print("== 等待接收服务启动 ==")
for _ in range(30):
    try:
        get("/api/health")
        break
    except Exception:
        time.sleep(0.5)
else:
    sys.exit("接收服务未启动")

print("\n[1] 接收服务托管的是新版申报页")
st, body = get("/")
html = body.decode("utf-8", "ignore")
ok(st == 200, "首页返回 200")
ok("eviBody" in html and "上传证据材料" in html, "托管页面含新版证据目录表格")
ok("dropzone" not in html and "certLegalBox" not in html, "旧上传区与扫描件槽位已不在页面中")
ok("＋ 添加一行" in html, "页面含「＋ 添加一行」按钮")
st2, b2 = get("/templates/%E6%8E%88%E6%9D%83%E5%A7%94%E6%89%98%E4%B9%A6%E6%A8%A1%E6%9D%BF.docx")
ok(st2 == 200 and len(b2) > 1000, "模板下载仍可用（授权委托书模板）")

print("\n[2] 提交带证据名称的材料")
resp = post_apply([
    ("借款合同-合同扫描件.pdf", b"%PDF-1.4 fake contract"),
    ("发票-增值税发票.pdf", b"%PDF-1.4 fake invoice"),
    ("未填证据名称的材料.txt", "纯文本材料".encode("utf-8")),
])
ok(resp.get("ok") is True, "提交成功", resp)
no = resp["submit_no"]
mf = json.loads((DATA / no / "manifest.json").read_text(encoding="utf-8"))
names = [f["name"] for f in mf["files"]]
ok(names == ["借款合同-合同扫描件.pdf", "发票-增值税发票.pdf", "未填证据名称的材料.txt"],
   "manifest 中文件名即证据目录（证据名称-原文件名）", names)
ok(all((DATA / no / f["stored"]).exists() for f in mf["files"]), "3 个材料文件均已落盘")
ok(mf["claim"]["amount"] == "856000.0", "申报金额落盘", mf["claim"]["amount"])

print("\n[3] 管理端拉取列表")
st, body = get("/api/admin/claims", token="testtoken")
rows = json.loads(body.decode())["claims"]
row = next((r for r in rows if r["submit_no"] == no), None)
ok(row is not None, "管理端可见该申报")
ok(row and row["file_count"] == 3, "文件数 3")
ok(row and all("借款合同" in n or "发票" in n or "未填" in n for n in row["files"]),
   "管理端文件列表可见证据名称", row["files"] if row else None)

print("\n[4] 收尾")
st, body = get(f"/api/admin/claims/{no}/package", token="testtoken")
ok(st == 200 and body[:2] == b"PK", "打包下载返回 ZIP")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 端到端联调全部通过")
