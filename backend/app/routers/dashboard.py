"""债权数据后台（Dashboard）统计接口：台账汇总 + 性质/金额/审核三组结论聚合。

债权性质口径（7 类标准）：购房者优先权 / 工程款优先权 / 抵押债权 /
职工债权 / 税收债权 / 普通债权 / 劣后债权。
审查结论三组：已审查确认（confirmed）/ 暂缓确认（partial）/ 已否定（rejected），
结论优先取人工复核结论（认可/部分认可/不认可），无人工结论时取 AI 审查结论。
支持 ?nature= 按债权性质筛选。
"""
import json
from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditResult, Claim
from .projects import get_project_or_404

router = APIRouter(prefix="/api/projects", tags=["dashboard"])

# 债权性质标准 7 类（固定顺序）
NATURE_ORDER = ["购房者优先权", "工程款优先权", "抵押债权", "职工债权",
                "税收债权", "普通债权", "劣后债权"]

# 历史数据归一（纯同义词/明显错位合并，归入标准 7 类）
NATURE_NORM = {
    "工程债权": "工程款优先权", "购房优先权": "购房者优先权",
    "购房者": "购房者优先权", "税收": "税收债权", "税款债权": "税收债权",
    "职工": "职工债权", "抵押": "抵押债权", "劣后": "劣后债权",
    "无担保": "普通债权",
}
# status 兼容：历史脏值映射到标准登记状态
STATUS_NORM = {"确认": "reviewed", "待定": "pending", "不予确认": "reviewed",
               "已确认": "reviewed"}

# 人工结论 → 三组；AI 结论（review_result）→ 三组
CONCL_GROUP = {"认可": "confirmed", "部分认可": "partial", "不认可": "rejected"}
AI_GROUP = {"confirmed": "confirmed", "partial": "partial", "rejected": "rejected"}
GROUPS = ("confirmed", "partial", "rejected")
GROUP_LABELS = {"confirmed": "已审查确认", "partial": "暂缓确认", "rejected": "已否定"}


def _norm(v, table: dict) -> str:
    v = (v or "").strip()
    return table.get(v, v)


def _nature_key(raw) -> str:
    """原始性质 → 标准 7 类之一；无法归类的归「未标注」。"""
    v = _norm(raw, NATURE_NORM)
    if v in NATURE_ORDER:
        return v
    return "未标注"


def _effective_nature(claim, concluded: bool = False) -> str:
    """债权性质口径：

    - 申报侧（concluded=False）：按申报性质 claim_nature 归类；
    - 已定论侧（concluded=True）：优先用人工复核确认的性质 debt_nature
      （仅当它能归入标准 7 类时），否则回退申报性质。
    """
    if concluded:
        dn = _nature_key(getattr(claim, "debt_nature", ""))
        if dn != "未标注":
            return dn
    return _nature_key(getattr(claim, "claim_nature", ""))


def _amt(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _conclusion_group(audit: AuditResult | None) -> str:
    """该债权的审查结论分组：人工结论优先，其次 AI 结论；都没有返回空串。"""
    if audit is None:
        return ""
    concl = (audit.audit_conclusion or "").strip()
    if concl in CONCL_GROUP:
        return CONCL_GROUP[concl]
    if audit.ai_status == "done" and audit.ai_opinion:
        try:
            rr = (json.loads(audit.ai_opinion).get("review_result") or "").strip()
        except (json.JSONDecodeError, AttributeError, TypeError):
            rr = ""
        if rr in AI_GROUP:
            return AI_GROUP[rr]
    return ""


@router.get("/{project_id}/dashboard")
def project_dashboard(project_id: int, nature: str = "",
                      db: Session = Depends(get_db)):
    """债权数据后台统计：总览 + 多维分布 + 审核情况（可按债权性质筛选）。"""
    get_project_or_404(db, project_id)
    claims = db.query(Claim).filter(Claim.project_id == project_id).all()

    # 按债权性质筛选（标准 7 类；空 = 全部）
    # 按债权性质筛选（标准 7 类；空 = 全部）；申报性质或复核确认性质命中即计入
    nature_filter = _nature_key(nature) if nature.strip() else ""
    if nature_filter:
        claims = [c for c in claims
                  if nature_filter in (_effective_nature(c, False),
                                       _effective_nature(c, True))]

    total = len(claims)

    def _sum(key):
        return sum(_amt(getattr(c, key)) for c in claims)

    # ---- 申报汇总 ----
    sum_claimed = _sum("claim_amount")
    sum_principal = _sum("principal")
    sum_interest = _sum("interest")
    sum_others = _sum("others")
    # ---- 审核汇总（有审核金额 = 已审查确认）----
    audited_claims = [c for c in claims if _amt(c.audited_amount) > 0]
    sum_audited = sum(_amt(c.audited_amount) for c in audited_claims)
    sum_audited_p = sum(_amt(c.audited_principal) for c in audited_claims)
    sum_audited_i = sum(_amt(c.audited_interest) for c in audited_claims)
    sum_audited_o = sum(_amt(c.audited_others) for c in audited_claims)

    # ---- 按债权性质：申报 + 审核（固定 7 类顺序 + 未标注）----
    def _nature_stats(items, amt_key, audited=False):
        agg = {n: {"count": 0, "amount": 0.0,
                   "principal": 0.0, "interest": 0.0, "others": 0.0}
               for n in NATURE_ORDER}
        agg["未标注"] = {"count": 0, "amount": 0.0,
                         "principal": 0.0, "interest": 0.0, "others": 0.0}
        for c in items:
            k = _effective_nature(c, concluded=audited)
            if audited:
                agg[k]["count"] += 1
                agg[k]["amount"] += _amt(c.audited_amount)
                agg[k]["principal"] += _amt(c.audited_principal)
                agg[k]["interest"] += _amt(c.audited_interest)
                agg[k]["others"] += _amt(c.audited_others)
            else:
                agg[k]["count"] += 1
                agg[k]["amount"] += _amt(c.claim_amount)
                agg[k]["principal"] += _amt(c.principal)
                agg[k]["interest"] += _amt(c.interest)
                agg[k]["others"] += _amt(c.others)
        return [{"name": n,
                 "count": agg[n]["count"],
                 "amount": round(agg[n]["amount"], 2),
                 "principal": round(agg[n]["principal"], 2),
                 "interest": round(agg[n]["interest"], 2),
                 "others": round(agg[n]["others"], 2)}
                for n in list(NATURE_ORDER) + ["未标注"]]

    nature_claimed = _nature_stats(claims, "claim_amount", audited=False)
    nature_audited = _nature_stats(audited_claims, "audited_amount", audited=True)

    # ---- 登记状态分布 ----
    status_count = {"pending": 0, "registered": 0, "reviewed": 0}
    for c in claims:
        s = STATUS_NORM.get(c.status, c.status)
        s = s if s in status_count else "pending"
        status_count[s] += 1

    # ---- AI 审查结论（基于 audit_results，仅统计当前筛选范围内）----
    claim_ids = {c.id for c in claims}
    audit_rows = db.query(AuditResult).filter(
        AuditResult.claim_id.in_(claim_ids)).all() if claim_ids else []
    audit_done = 0
    audit_by_result = defaultdict(lambda: {"count": 0, "amount": 0.0})
    claim_audit_map = {c.id: _amt(c.audited_amount) for c in audited_claims}
    for a in audit_rows:
        if a.ai_status != "done":
            continue
        audit_done += 1
        rr = "partial"
        if a.ai_opinion:
            try:
                rr = (json.loads(a.ai_opinion).get("review_result") or "partial")
            except (json.JSONDecodeError, AttributeError):
                pass
        audit_by_result[rr]["count"] += 1
        audit_by_result[rr]["amount"] += claim_audit_map.get(a.claim_id, 0.0)
    audit_result_list = [
        {"name": "已认可", "count": audit_by_result["confirmed"]["count"],
         "amount": round(audit_by_result["confirmed"]["amount"], 2)},
        {"name": "部分认可", "count": audit_by_result["partial"]["count"],
         "amount": round(audit_by_result["partial"]["amount"], 2)},
        {"name": "不予认可", "count": audit_by_result["rejected"]["count"],
         "amount": round(audit_by_result["rejected"]["amount"], 2)}]

    # ---- 审查结论三组汇总：已审查确认 / 暂缓确认 / 已否定 ----
    # 笔数 + 金额（本金/利息/其他），并保留按债权性质的明细
    # 金额口径：该笔已有审核金额则取审核金额，否则取申报金额（在 amount_basis 标注）
    audit_by_claim = {a.claim_id: a for a in audit_rows}
    group_agg = {
        g: {"count": 0, "amount": 0.0, "principal": 0.0, "interest": 0.0,
            "others": 0.0, "claimed_amount": 0.0, "audited_amount": 0.0,
            "nature": {n: {"count": 0, "amount": 0.0}
                       for n in list(NATURE_ORDER) + ["未标注"]}}
        for g in GROUPS
    }
    no_conclusion = 0
    for c in claims:
        g = _conclusion_group(audit_by_claim.get(c.id))
        if not g:
            no_conclusion += 1
            continue
        has_audited = any(_amt(getattr(c, k)) > 0 for k in
                          ("audited_amount", "audited_principal",
                           "audited_interest", "audited_others"))
        amount = _amt(c.audited_amount) if has_audited else _amt(c.claim_amount)
        p = _amt(c.audited_principal) if has_audited else _amt(c.principal)
        i = _amt(c.audited_interest) if has_audited else _amt(c.interest)
        o = _amt(c.audited_others) if has_audited else _amt(c.others)
        agg = group_agg[g]
        agg["count"] += 1
        agg["amount"] += amount
        agg["principal"] += p
        agg["interest"] += i
        agg["others"] += o
        agg["claimed_amount"] += _amt(c.claim_amount)
        agg["audited_amount"] += _amt(c.audited_amount)
        nk = _effective_nature(c, concluded=True)
        agg["nature"][nk]["count"] += 1
        agg["nature"][nk]["amount"] += amount

    def _group_out(g: str) -> dict:
        a = group_agg[g]
        return {
            "label": GROUP_LABELS[g],
            "count": a["count"],
            "amount": round(a["amount"], 2),
            "principal": round(a["principal"], 2),
            "interest": round(a["interest"], 2),
            "others": round(a["others"], 2),
            "claimed_amount": round(a["claimed_amount"], 2),
            "audited_amount": round(a["audited_amount"], 2),
            "nature": [{"name": n, "count": a["nature"][n]["count"],
                        "amount": round(a["nature"][n]["amount"], 2)}
                       for n in list(NATURE_ORDER) + ["未标注"]],
        }

    audit_groups = {g: _group_out(g) for g in GROUPS}
    audit_groups["no_conclusion"] = no_conclusion

    return {
        "total": total,
        "nature_filter": nature_filter,
        "overview": {
            "count": total,
            "sum_claimed": round(sum_claimed, 2),
            "sum_principal": round(sum_principal, 2),
            "sum_interest": round(sum_interest, 2),
            "sum_others": round(sum_others, 2),
            # 审核侧
            "audited_count": len(audited_claims),
            "sum_audited": round(sum_audited, 2),
            "sum_audited_principal": round(sum_audited_p, 2),
            "sum_audited_interest": round(sum_audited_i, 2),
            "sum_audited_others": round(sum_audited_o, 2),
            "reviewed": status_count["reviewed"],
            "registered": status_count["registered"],
            "pending": status_count["pending"],
        },
        "nature_claimed": nature_claimed,
        "nature_audited": nature_audited,
        "by_status": status_count,
        "audit": {
            "done": audit_done,
            "total_audit_rows": len(audit_rows),
            "by_result": audit_result_list,
        },
        "audit_groups": audit_groups,
    }
