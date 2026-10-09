"""数据后台新统计口径验证（真实数据，只读）。

校验：审查结论三组（确认/暂缓/否定）的笔数、金额、本金利息其他；
已确认组按债权性质明细；以及已删除的字段（by_category / brackets）不再返回。

运行：python _test_dashboard_groups.py
"""
import json
import sys
import urllib.request

BASE = "http://127.0.0.1:8000"
fails = []


def ok(cond, label, extra=""):
    print(("  ✅ " if cond else "  ❌ ") + label + ("" if cond else f"  → {extra}"))
    if not cond:
        fails.append(label)


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return json.loads(r.read().decode())


print("== 读取项目与看板数据 ==")
projects = get("/api/projects")
pid = projects[0]["id"]
d = get(f"/api/projects/{pid}/dashboard")
claims = get(f"/api/claims?project_id={pid}")
print(f"  项目：{projects[0]['name']}（{len(claims)} 笔）")

print("\n[1] 接口结构")
ok("audit_groups" in d, "返回 audit_groups（三组汇总）")
for k in ("by_category", "brackets"):
    ok(k not in d, f"不再返回已删除的字段 {k}", list(d.keys()))
g = d.get("audit_groups") or {}
for key in ("confirmed", "partial", "rejected"):
    ok(key in g, f"含分组 {key}")
ok(isinstance(g.get("no_conclusion"), int), "含未出结论笔数 no_conclusion", g.get("no_conclusion"))

print("\n[2] 每组字段完整性（笔数 + 金额 + 本金/利息/其他 + 性质明细）")
for key in ("confirmed", "partial", "rejected"):
    grp = g.get(key) or {}
    fields = ["label", "count", "amount", "principal", "interest", "others",
              "claimed_amount", "audited_amount", "nature"]
    ok(all(f in grp for f in fields), f"{key} 字段齐全", [f for f in fields if f not in grp])
    nat = grp.get("nature") or []
    names = [x["name"] for x in nat]
    ok(len(nat) == 8 and "购房者优先权" in names and "工程款优先权" in names,
       f"{key} 含 7 类性质 + 未标注明细", names)

print("\n[3] 与台账逐笔核对（人工结论优先，其次 AI 结论）")
# 用 raw 数据自行复算一遍三组，与接口结果比对
audit_by_claim = {}
for c in claims:
    a = get(f"/api/claims/{c['id']}/audit")
    if a and a.get("id"):
        audit_by_claim[c["id"]] = a


def amt(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def group_of(a):
    if not a:
        return ""
    concl = (a.get("audit_conclusion") or "").strip()
    if concl == "认可":
        return "confirmed"
    if concl == "部分认可":
        return "partial"
    if concl == "不认可":
        return "rejected"
    if a.get("ai_status") == "done" and a.get("ai_opinion"):
        try:
            rr = (json.loads(a["ai_opinion"]).get("review_result") or "").strip()
        except Exception:  # noqa: BLE001
            rr = ""
        return rr if rr in ("confirmed", "partial", "rejected") else ""
    return ""


def nature_key(raw):
    v = (raw or "").strip()
    norm = {"工程债权": "工程款优先权", "购房优先权": "购房者优先权", "购房者": "购房者优先权",
            "税收": "税收债权", "税款债权": "税收债权", "职工": "职工债权",
            "抵押": "抵押债权", "劣后": "劣后债权", "无担保": "普通债权"}
    v = norm.get(v, v)
    return v if v in ("购房者优先权", "工程款优先权", "抵押债权", "职工债权",
                      "税收债权", "普通债权", "劣后债权") else "未标注"


def effective_nature(c, concluded=False):
    """已定论侧优先取复核确认性质 debt_nature（能归入 7 类时）。"""
    if concluded:
        dn = nature_key(c.get("debt_nature"))
        if dn != "未标注":
            return dn
    return nature_key(c.get("claim_nature"))


manual_done = [c for c in claims if (audit_by_claim.get(c["id"]) or {}).get("manual_status") == "done"]
print(f"  台账中已完成人工复核的债权：{len(manual_done)} 笔")
exp = {k: {"count": 0, "amount": 0.0, "p": 0.0, "i": 0.0, "o": 0.0} for k in
       ("confirmed", "partial", "rejected")}
exp_nature = {k: {} for k in ("confirmed", "partial", "rejected")}
for c in claims:
    gg = group_of(audit_by_claim.get(c["id"]))
    if not gg:
        continue
    has_aud = any(amt(c.get(k)) > 0 for k in
                  ("audited_amount", "audited_principal", "audited_interest", "audited_others"))
    amount = amt(c["audited_amount"]) if has_aud else amt(c["claim_amount"])
    exp[gg]["count"] += 1
    exp[gg]["amount"] += amount
    exp[gg]["p"] += amt(c["audited_principal"]) if has_aud else amt(c["principal"])
    exp[gg]["i"] += amt(c["audited_interest"]) if has_aud else amt(c["interest"])
    exp[gg]["o"] += amt(c["audited_others"]) if has_aud else amt(c["others"])
    nk = effective_nature(c, concluded=True)
    cell = exp_nature[gg].setdefault(nk, {"count": 0, "amount": 0.0})
    cell["count"] += 1
    cell["amount"] += amount

for key in ("confirmed", "partial", "rejected"):
    grp = g.get(key) or {}
    ok(grp.get("count") == exp[key]["count"], f"{key} 笔数一致", {"api": grp.get("count"), "calc": exp[key]["count"]})
    for f, label in (("amount", "金额"), ("principal", "本金"), ("interest", "利息"), ("others", "其他")):
        api_v = round(float(grp.get(f) or 0), 2)
        calc_v = round(exp[key][{"amount": "amount", "principal": "p", "interest": "i", "others": "o"}[f]], 2)
        ok(abs(api_v - calc_v) < 0.02, f"{key} {label}一致", {"api": api_v, "calc": calc_v})

print("\n[3.5] 性质明细逐类核对（已定论侧优先用复核确认性质）")
for key in ("confirmed", "partial", "rejected"):
    api_nat = {x["name"]: x for x in (g.get(key) or {}).get("nature", []) if x["count"] > 0}
    calc_nat = exp_nature[key]
    ok(set(api_nat) == set(calc_nat), f"{key} 性质分类集合一致",
       {"api": sorted(api_nat), "calc": sorted(calc_nat)})
    for nk, v in calc_nat.items():
        a = api_nat.get(nk) or {}
        ok(a.get("count") == v["count"] and abs(round(float(a.get("amount") or 0), 2) - round(v["amount"], 2)) < 0.02,
           f"{key} · {nk} 笔数/金额一致", {"api": a, "calc": v})

print("\n[4] 三组笔数 + 未出结论 = 申报总笔数")
total_g = sum((g.get(k) or {}).get("count", 0) for k in ("confirmed", "partial", "rejected")) + g.get("no_conclusion", 0)
ok(total_g == d["total"], "三组 + 未出结论 = 总笔数", {"sum": total_g, "total": d["total"]})

print("\n[5] 明细打印（供人工核对）")
for key in ("confirmed", "partial", "rejected"):
    grp = g.get(key) or {}
    nat = [x for x in (grp.get("nature") or []) if x["count"] > 0]
    print(f"  {grp.get('label')}: {grp.get('count')} 笔 · {grp.get('amount'):,.2f} 元"
          f"（本金 {grp.get('principal'):,.2f} / 利息 {grp.get('interest'):,.2f} / 其他 {grp.get('others'):,.2f}）")
    print("     性质：" + ("；".join(f"{x['name']} {x['count']}笔 {x['amount']:,.2f}" for x in nat) or "无"))
print(f"  尚未出结论：{g.get('no_conclusion')} 笔")

print("\n================ 结果 ================")
if fails:
    print(f"❌ {len(fails)} 项未通过：")
    for f in fails:
        print("   - " + f)
    sys.exit(1)
print("✅ 数据后台新口径全部通过")
