"""初审/编辑流程改造端到端验证（真实接口，用临时项目，跑完即删）。

覆盖：
1. 保存初审/编辑 → 状态自动变「已登记」
2. 取消登记 → 回到「待登记」（材料与审查记录保留）
3. 申报总额 = 本金+利息+其他；审核总额 = 审核本金+审核利息+审核其他（保存即汇总）
4. 名称为空保存 → 不自动登记

运行：python _test_edit_register.py
"""
import json
import sys
import time
import urllib.request

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
        b = "----edittest"
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


print("== 准备临时项目与债权 ==")
for p in req("GET", "/api/projects"):
    if p["name"].startswith("初审编辑测试"):
        for cl in req("GET", f"/api/claims?project_id={p['id']}"):
            req("DELETE", f"/api/claims/{cl['id']}")
        req("DELETE", f"/api/projects/{p['id']}")

pid = req("POST", "/api/projects", json_body={"name": "初审编辑测试（自动清理）", "case_no": "TEST-EDIT"})["id"]
cid = req("POST", f"/api/projects/{pid}/upload",
          files=[("材料.txt", "债权人：初审测试公司\n本金：100000元\n".encode("utf-8"))])["id"]
time.sleep(6)
c = req("GET", f"/api/claims/{cid}")
print(f"  项目 {pid}，债权 {cid}（{c['claim_no']}）初始状态={c['status']}")
ok(c["status"] == "pending", "新建债权初始为「待登记」", c["status"])
try:
    print("\n[1] 保存初审/编辑 → 自动登记 + 总额自动汇总")
    r = req("PUT", f"/api/claims/{cid}", json_body={
        "name": "初审测试公司", "credit_code": "91500000TEST",
        "principal": 100000, "interest": 20000, "others": 5000,
        "audited_principal": 90000, "audited_interest": 18000, "audited_others": 4000,
    })
    ok(r["status"] == "registered", "保存后状态自动变为「已登记」", r["status"])
    ok(abs(float(r["claim_amount"]) - 125000) < 0.01,
       "申报总额自动汇总 = 本金+利息+其他 = 125000", r["claim_amount"])
    ok(abs(float(r["audited_amount"]) - 112000) < 0.01,
       "审核总额自动汇总 = 审核本金+利息+其他 = 112000", r["audited_amount"])

    print("\n[2] 只改一个分项也重新汇总")
    r = req("PUT", f"/api/claims/{cid}", json_body={"interest": 30000})
    ok(abs(float(r["claim_amount"]) - 135000) < 0.01, "改利息后申报总额=100000+30000+5000=135000", r["claim_amount"])
    r = req("PUT", f"/api/claims/{cid}", json_body={"audited_others": 0})
    ok(abs(float(r["audited_amount"]) - 108000) < 0.01,
       "改审核其他后审核总额=90000+18000+0=108000", r["audited_amount"])

    print("\n[3] 分项全为 0 时不误清总额（保护历史数据）")
    r = req("PUT", f"/api/claims/{cid}", json_body={"claim_amount": 999999})
    ok(abs(float(r["claim_amount"]) - 999999) < 0.01, "显式传总额时按传入保存", r["claim_amount"])
    r = req("PUT", f"/api/claims/{cid}", json_body={"others": 0, "interest": 30000, "principal": 100000})
    ok(abs(float(r["claim_amount"]) - 130000) < 0.01, "分项有值时仍按分项汇总覆盖", r["claim_amount"])

    print("\n[4] 取消登记")
    r = req("POST", f"/api/claims/{cid}/unregister")
    ok(r["status"] == "pending", "取消登记后状态回到「待登记」", r["status"])
    files = req("GET", f"/api/claims/{cid}/detail")["files"]
    ok(len(files) == 1, "材料文件保留", len(files))
    r2 = req("PUT", f"/api/claims/{cid}", json_body={"name": "初审测试公司"})
    ok(r2["status"] == "registered", "再次保存又自动登记", r2["status"])

    print("\n[5] 待登记状态下取消登记应被拒绝")
    req("POST", f"/api/claims/{cid}/unregister")
    try:
        req("POST", f"/api/claims/{cid}/unregister")
        ok(False, "重复取消登记应报错")
    except urllib.error.HTTPError as e:
        ok(e.code == 400, "已是待登记时返回 400", e.code)

    print("\n[6] 名为空保存 → 不自动登记")
    cid2 = req("POST", f"/api/projects/{pid}/upload",
               files=[("无名称材料.txt", b"no name here")])["id"]
    time.sleep(5)
    r = req("PUT", f"/api/claims/{cid2}", json_body={"principal": 1000})
    ok(r["status"] == "pending", "未填名称时保存仍为「待登记」", r["status"])
    ok(abs(float(r["claim_amount"]) - 1000) < 0.01, "金额仍正常汇总", r["claim_amount"])

    print("\n[7] 已复核债权的取消登记")
    req("PUT", f"/api/claims/{cid2}", json_body={"name": "第二测试公司", "principal": 1000})
    req("POST", f"/api/claims/{cid2}/manual-audit", json_body={
        "manual_opinion": "复核意见", "audit_conclusion": "认可", "auditor": "测试人",
        "audited_principal": 1000, "audited_amount": 1000})
    c2 = req("GET", f"/api/claims/{cid2}")
    ok(c2["status"] == "reviewed", "人工复核后为「已复核」", c2["status"])
    r = req("POST", f"/api/claims/{cid2}/unregister")
    ok(r["status"] == "pending", "已复核也可取消登记 → 待登记", r["status"])
    a = req("GET", f"/api/claims/{cid2}/audit")
    ok(a["manual_status"] == "done" and "复核意见" in (a.get("manual_opinion") or ""),
       "取消登记保留人工复核记录", a["manual_status"])
finally:
    print("\n== 清理 ==")
    for cl in req("GET", f"/api/claims?project_id={pid}"):
        req("DELETE", f"/api/claims/{cl['id']}")
    req("DELETE", f"/api/projects/{pid}")
    left = [x for x in req("GET", "/api/projects") if x["id"] == pid]
    ok(not left, "临时项目已删除")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 初审/编辑流程改造全部通过")
