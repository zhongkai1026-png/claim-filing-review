"""审查 API：AI 审查（后台线程）、审查状态、人工复核、意见书编辑。"""
import json
import threading
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import AuditResult, Claim, Project
from ..schemas import AuditResultOut, ManualAuditIn
from ..services import auditor, exporter, llm

router = APIRouter(prefix="/api", tags=["audit"])


def get_audit_or_404(db: Session, claim_id: int) -> AuditResult:
    a = db.query(AuditResult).filter(AuditResult.claim_id == claim_id).first()
    if not a:
        raise HTTPException(404, "审查记录不存在，请先执行 AI 审查")
    return a


@router.post("/claims/{claim_id}/ai-audit")
def start_ai_audit(claim_id: int, db: Session = Depends(get_db)):
    """启动 AI 审查（后台执行，前端轮询状态）。"""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "债权记录不存在")
    # 确保有审查记录行
    result = db.query(AuditResult).filter(
        AuditResult.claim_id == claim_id).first()
    if not result:
        result = AuditResult(claim_id=claim_id)
        db.add(result)
    result.ai_status = "running"
    result.ai_error = ""                    # 清空上次错误
    result.ai_started_at = datetime.now()   # 记录启动时间（本地时间基准）
    db.commit()

    if not llm.get_active_config():
        # 未配置激活模型：直接跑规则引擎
        def _rule():
            auditor.run_rule_audit(claim_id)
        threading.Thread(target=_rule, daemon=True).start()
    else:
        threading.Thread(target=auditor.run_ai_audit, args=(claim_id,),
                         daemon=True).start()
    return {"ok": True, "ai_status": "running"}


@router.get("/claims/{claim_id}/audit", response_model=AuditResultOut)
def get_audit(claim_id: int, db: Session = Depends(get_db)):
    a = db.query(AuditResult).filter(AuditResult.claim_id == claim_id).first()
    if not a:
        # 无审查记录：返回空状态对象（避免前端/校验报错）
        return AuditResultOut(id=0, claim_id=claim_id,
                              created_at=datetime.now())
    # 自愈：running 超过 15 分钟视为中断（服务重启 / 线程异常退出）。
    # 仅依据 ai_started_at（与 datetime.now() 同为本地时间基准），
    # 避免历史数据 updated_at 使用 UTC 导致误判。
    if a.ai_status == "running" and a.ai_started_at:
        if (datetime.now() - a.ai_started_at).total_seconds() > 900:
            a.ai_status = "failed"
            a.ai_error = "审查中断（服务重启或执行超时），请重新点击「AI 审查」"
            db.commit()
            db.refresh(a)
    return a


@router.post("/claims/{claim_id}/manual-audit")
def manual_audit(claim_id: int, body: ManualAuditIn,
                 db: Session = Depends(get_db)):
    """人工复核：保存意见 + 审核金额 + 确认债权性质，状态置为已复核。"""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "债权记录不存在")
    audited = body.model_dump(exclude_unset=True)
    audited = {k: v for k, v in audited.items()
               if k in ("audited_principal", "audited_interest",
                        "audited_others", "audited_amount") and v is not None}
    # 人工复核确定的债权性质同步到台账 debt_nature（7 类标准）
    if body.debt_nature:
        claim.debt_nature = body.debt_nature
        db.commit()
    auditor.save_manual_audit(
        claim_id, body.manual_opinion or "", body.audit_conclusion or "",
        body.auditor or "", audited or None)
    return {"ok": True}


# ---------------- 意见书：预览/编辑/保存 ----------------

def _get_result(db: Session, claim_id: int) -> AuditResult | None:
    return db.query(AuditResult).filter(
        AuditResult.claim_id == claim_id).first()


@router.get("/claims/{claim_id}/opinion-preview")
def opinion_preview(claim_id: int, db: Session = Depends(get_db)):
    """意见书预览/编辑数据（固定表格 + 可编辑文本块）。"""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "债权记录不存在")
    project = db.get(Project, claim.project_id)
    result = _get_result(db, claim_id)
    data = exporter.opinion_preview_data(project, claim, result)
    data["claim_id"] = claim_id
    data["claim_no"] = claim.claim_no
    data["project_name"] = project.name if project else ""
    data["debtor"] = project.debtor if project else ""
    data["manager"] = project.manager if project else ""
    data["claim_date"] = claim.claim_date or ""
    return data


@router.post("/claims/{claim_id}/opinion-draft")
def save_opinion_draft(claim_id: int,
                       body: dict = Body(...),
                       db: Session = Depends(get_db)):
    """保存意见书编辑稿（最终内容，导出优先使用）。"""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "债权记录不存在")
    result = _get_result(db, claim_id)
    if not result:
        result = AuditResult(claim_id=claim_id)
        db.add(result)
    # 仅保留允许的键，避免脏数据
    allowed = ("checks", "reason", "material_evidence", "diff_reason",
               "legal_basis", "conclusion")
    clean = {k: v for k, v in (body or {}).items() if k in allowed}
    result.opinion_draft = json.dumps(clean, ensure_ascii=False)
    # 编辑稿的 conclusion 同步为审查结论（中文：认可/部分认可/不认可）
    if clean.get("conclusion"):
        result.audit_conclusion = str(clean["conclusion"])
    db.commit()
    return {"ok": True, "saved": True}
