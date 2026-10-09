"""确认服务托管的前端与数据库状态（UTF-8 正确解码）。"""
import json
import sqlite3
import urllib.request

app = urllib.request.urlopen("http://127.0.0.1:8000/js/app.js", timeout=10).read().decode("utf-8")
print("== 前端版本标记（正确解码）==")
for k in ["台账数据", "数据进出", "新增债权申报", "初审 / 编辑", "取消登记", "补充材料",
          "已人工确认", "系统解析预填", "view-tabs", "rowMenuPop", "batchBar",
          "acceptDateWarningHtml", "ledgerActionAreaHtml"]:
    print(f"  {'✅' if k in app else '❌'} {k}")

print("\n== 张军(132) 的审查记录 ==")
c = sqlite3.connect(r"D:\Deepseek\培训-债权申报与审查\backend\data\claims.db")
c.row_factory = sqlite3.Row
a = c.execute("select * from audit_results where claim_id=132").fetchone()
if a:
    print("  ai_status:", a["ai_status"], "| prompt_version:", a["prompt_version"],
          "| 注入标准:", repr(a["injected_standards"]))
    print("  注入案件信息:", (a["injected_case_info"] or "")[:160].replace("\n", " / "))
    op = json.loads(a["ai_opinion"] or "{}")
    for s in (op.get("review_process") or [])[:2]:
        print(f"    第{s.get('level')}级 {s.get('name')}：{str(s.get('detail'))[:120]}")
else:
    print("  无审查记录")

print("\n== 各表格行数 ==")
for t in ("projects", "claims", "claim_files", "audit_results"):
    print(f"  {t}: {c.execute(f'select count(*) from {t}').fetchone()[0]}")
print("  标记为人工确认的债权:", c.execute("select count(*) from claims where verified_at is not null").fetchone()[0])
c.close()
