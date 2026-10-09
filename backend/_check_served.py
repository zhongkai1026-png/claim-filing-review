"""确认服务托管的前端文件已含最新改动。"""
import urllib.request

app = urllib.request.urlopen("http://127.0.0.1:8000/js/app.js", timeout=10).read().decode("utf-8")
css = urllib.request.urlopen("http://127.0.0.1:8000/css/style.css", timeout=10).read().decode("utf-8")

checks_app = ["unregisterClaim", "取消登记", "已保存并自动登记", "自动汇总", "初审 / 编辑",
              "audit_groups", "dashPie", "ledgerActionAreaHtml", "rowMenuPop", "batchAiAudit"]
for k in checks_app:
    print(f"  app.js 含 {k:<20} {k in app}")
print("---")
for k in ["col-actions", "view-tab", "row-menu-pop", "action-card", "dash-group"]:
    print(f"  css    含 {k:<20} {k in css}")
