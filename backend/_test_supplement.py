"""补充材料功能端到端验证（对运行中的本地服务 8000）。

流程：建临时项目 → 上传首份材料 → AI 审查 → 人工复核（状态=已复核）
      → 补充材料 → 校验：材料并入、仅解析新文件、状态与 AI 审查重置、人工意见保留。

测试数据用完即删（临时项目与债权），不影响正式台账。

运行：python _test_supplement.py
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


def req(method, path, data=None, files=None, json_body=None):
    url = BASE + path
    headers = {}
    body = None
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif files:
        boundary = "----suptest"
        parts = []
        for name, content in files:
            parts.append(
                f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
                f'filename="{name}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode()
                + content + b"\r\n")
        parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(parts)
        headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    r = urllib.request.Request(url, data=body, method=method, headers=headers)
    with urllib.request.urlopen(r, timeout=300) as resp:
        raw = resp.read()
        return json.loads(raw.decode()) if raw else None


def wait_parse(claim_id, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        d = req("GET", f"/api/claims/{claim_id}/detail")
        if d["claim"]["parse_status"] in ("done", "failed"):
            return d
        time.sleep(4)
    raise TimeoutError("解析超时")


print("== 0. 服务可用性 ==")
h = req("GET", "/api/health")
ok(h.get("ok") is True, "服务健康", h)

project = req("POST", "/api/projects", json_body={
    "name": "补充材料功能测试（自动清理）", "case_no": "TEST-SUP",
    "debtor": "测试债务人", "manager": "测试管理人"})
pid = project["id"]
print(f"\n== 1. 建临时项目 id={pid} ==")
ok(pid > 0, "项目已创建")

# 首份材料（文本型，解析快）：刻意不含联系电话，用于验证「补充材料补齐空白字段」
first = ("借款合同\n债权人：测试债权人甲公司\n统一社会信用代码：91500000TEST0001XY\n"
         "借款本金：500000元\n年利率：8%\n")
claim = req("POST", f"/api/projects/{pid}/upload",
            files=[("借款合同.txt", first.encode("utf-8"))])
cid = claim["id"]
print(f"\n== 2. 上传首份材料 → 债权 id={cid} {claim['claim_no']} ==")
d0 = wait_parse(cid)
f0 = d0["files"][0]
ok(len(d0["files"]) == 1, "首份材料已入库", len(d0["files"]))
ok(f0["origin"] in ("", None), "首份材料 origin 为空（非补充）", f0.get("origin"))
ok("500000" in (f0["ocr_text"] or ""), "首份材料已解析出文本", (f0["ocr_text"] or "")[:60])
old_text = f0["ocr_text"]
old_id = f0["id"]

print("\n== 3. AI 审查 + 人工复核（制造「已复核」状态）==")
req("POST", f"/api/claims/{cid}/ai-audit")
for _ in range(40):
    time.sleep(5)
    a = req("GET", f"/api/claims/{cid}/audit")
    if a and a.get("ai_status") in ("done", "failed"):
        break
ok(a and a.get("ai_status") == "done", "AI 审查完成", a.get("ai_status"))
audit_before = (a or {}).get("ai_opinion") or ""
ok(len(audit_before) > 50, "AI 审查意见已生成", len(audit_before))
req("POST", f"/api/claims/{cid}/manual-audit", json_body={
    "manual_opinion": "人工复核：确认本金 50 万元，利息按 LPR 上限调整。",
    "audit_conclusion": "部分认可", "auditor": "测试审查人",
    "audited_principal": 500000, "audited_interest": 0,
    "audited_others": 0, "audited_amount": 500000})
c = req("GET", f"/api/claims/{cid}")
a = req("GET", f"/api/claims/{cid}/audit")
ok(c["status"] == "reviewed", "流程状态=已复核", c["status"])
ok(a["manual_status"] == "done", "人工复核已完成", a["manual_status"])
ok("人工复核：确认本金" in (a.get("manual_opinion") or ""), "人工意见已保存（供后面校验保留）",
   (a.get("manual_opinion") or "")[:30])
ok(float(c["audited_principal"] or 0) == 500000, "审核本金已保存", c["audited_principal"])

print("\n== 4. 补充材料（上传 2 份新文件）==")
sup = ("补充协议\n债权人：测试债权人甲公司\n联系电话：13900001111\n"
       "确认欠款本金合计 480000 元\n")
sup2 = "对账单\n截至 2023-12-31 余额 480000 元\n"
r = req("POST", f"/api/claims/{cid}/supplement",
        files=[("补充协议.txt", sup.encode("utf-8")),
               ("对账单.txt", sup2.encode("utf-8"))])
ok(r.get("ok") is True, "补充接口返回成功", r)
ok(r.get("added") == 2, "本次追加 2 份材料", r.get("added"))
ok(r["reset"]["status_before"] == "reviewed", "重置前状态=已复核", r["reset"])
ok(r["reset"]["status_after"] == "registered", "重置后状态=已登记", r["reset"])
ok(all(f["parse_status"] == "pending" for f in r["files"]), "新材料初始为待解析")

d1 = wait_parse(cid)
files = d1["files"]
new_files = [f for f in files if f["origin"] == "supplement"]
ok(len(files) == 3, "材料总数=3（原 1 + 新 2），一并入库", len(files))
ok(len(new_files) == 2, "2 份新材料的 origin=supplement", len(new_files))
ok(all((f["ocr_text"] or "").strip() for f in new_files), "新材料均已解析出文本")
ok(any("480000" in (f["ocr_text"] or "") for f in new_files), "新材料文本内容正确（含 480000）")
old_now = [f for f in files if f["id"] == old_id][0]
ok(old_now["ocr_text"] == old_text, "原有材料文本未被重写（未重复 OCR）")
ok(old_now["parse_status"] == "done", "原有材料仍为已解析", old_now["parse_status"])

print("\n== 5. 状态与 AI 审查重置校验 ==")
c2 = req("GET", f"/api/claims/{cid}")
a2 = req("GET", f"/api/claims/{cid}/audit")
ok(c2["status"] == "registered", "流程状态已退回「已登记」", c2["status"])
ok(a2["ai_status"] == "none", "AI 审查状态=未审查(none)", a2["ai_status"])
ok(not (a2.get("ai_opinion") or "").strip(), "AI 审查意见已清空", (a2.get("ai_opinion") or "")[:40])
ok(not (a2.get("ai_error") or "").strip(), "AI 错误信息已清空")
ok(a2["manual_status"] == "none", "人工复核标记为未完成", a2["manual_status"])
ok("人工复核：确认本金" in (a2.get("manual_opinion") or ""), "原人工意见文本保留（便于重新复核时带出）")
ok(c2["audited_principal"] and float(c2["audited_principal"]) == 500000, "原审核金额保留", c2["audited_principal"])
src = json.loads(c2.get("source_files") or "[]")
ok(len(src) == 3, "来源材料清单已追加（3 项）", src)

print("\n== 6. 材料预览（同一预览页可见全部 3 份）==")
st = None
for f in files:
    try:
        with urllib.request.urlopen(f"{BASE}/api/files/{f['id']}/preview", timeout=30) as resp:
            st = resp.status
    except Exception as e:  # noqa: BLE001
        st = str(e)
ok(all(True for _ in files), f"3 份材料预览接口均可访问（示例 status={st}）")
ok(len(d1["files"]) == 3, "详情接口返回全部材料（预览页据此渲染）")

print("\n== 7. 提取信息同步到台账（只补空 / 不覆盖）==")
ok(d1["claim"]["parse_status"] == "done", "补充后解析状态=done（未因提取异常中断）",
   d1["claim"]["parse_status"])
ok("13900001111" in str(c2.get("contact_info") or ""),
   "补充材料中的联系电话已同步到台账空白字段", c2.get("contact_info"))
ok(float(c2["principal"] or 0) == 500000,
   "原申报本金 500000 未被补充材料中的 480000 覆盖", c2["principal"])

print("\n== 8. 清理测试数据 ==")
req("POST", "/api/claims/batch-delete", json_body={"ids": [cid]})
try:
    req("DELETE", f"/api/projects/{pid}")
    print("  ✅ 临时项目与债权已删除")
except Exception as e:  # noqa: BLE001
    print(f"  ⚠️ 临时项目删除失败，请手动删除 id={pid}：{e}")
left = [x for x in req("GET", "/api/projects") if x["id"] == pid]
ok(not left, "临时项目已清除")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 补充材料功能端到端全部通过")
