"""导出 API：Excel/CSV 台账、Word 审查意见书、批量 zip。"""
import re
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, Project
from ..services import exporter
from .projects import get_project_or_404

router = APIRouter(prefix="/api/export", tags=["export"])


def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "_", s)


def _content_disposition(fname: str) -> str:
    """构造兼容中文文件名的 Content-Disposition（RFC 5987）。"""
    ascii_name = fname.encode("ascii", "ignore").decode().strip() or "export"
    quoted = quote(fname)
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def _pick_claims(db: Session, project_id: int, ids: str = "") -> list[Claim]:
    """取要导出的债权：ids 为空导出整项目，否则只导出选中的（按传入顺序）。"""
    claims = db.query(Claim).filter(Claim.project_id == project_id).all()
    wanted = [int(x) for x in re.split(r"[,\s]+", ids or "") if x.strip().isdigit()]
    if not wanted:
        return claims
    order = {cid: i for i, cid in enumerate(wanted)}
    picked = [c for c in claims if c.id in order]
    picked.sort(key=lambda c: order[c.id])
    return picked


@router.get("/ledger")
def export_ledger(project_id: int, ids: str = "", db: Session = Depends(get_db)):
    """导出台账 Excel（.xlsx，可直接作为导入模板）；ids 非空时只导出选中债权。"""
    project = get_project_or_404(db, project_id)
    claims = _pick_claims(db, project_id, ids)
    if not claims:
        raise HTTPException(400, "没有可导出的债权记录")
    data = exporter.export_ledger(project, claims)
    media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    fname = f"债权申报台账_{_safe_name(project.name)}_{datetime.now():%Y%m%d}.xlsx"
    return Response(content=data, media_type=media,
                    headers={"Content-Disposition": _content_disposition(fname)})


@router.get("/opinion/{claim_id}")
def export_opinion(claim_id: int, db: Session = Depends(get_db)):
    """导出单份债权审查意见书 Word。"""
    claim = db.get(Claim, claim_id)
    if not claim:
        raise HTTPException(404, "债权记录不存在")
    project = db.get(Project, claim.project_id)
    data = exporter.export_opinion(project, claim)
    fname = f"债权审查意见书_{_safe_name(claim.claim_no)}_{_safe_name(claim.name)}.docx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": _content_disposition(fname)})


@router.get("/opinions")
def export_opinions(project_id: int, ids: str = "",
                    db: Session = Depends(get_db)):
    """批量导出审查意见书 zip；ids 非空时只导出选中债权。"""
    project = get_project_or_404(db, project_id)
    claims = _pick_claims(db, project_id, ids)
    if not claims:
        raise HTTPException(400, "没有可导出的债权记录")
    data = exporter.export_opinions_zip(project, claims)
    fname = f"审查意见书合集_{_safe_name(project.name)}_{datetime.now():%Y%m%d}.zip"
    return Response(content=data, media_type="application/zip",
                    headers={"Content-Disposition": _content_disposition(fname)})
