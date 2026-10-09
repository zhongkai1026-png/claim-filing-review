"""项目（破产案件）管理 API。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Claim, Project
from ..schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def get_project_or_404(db: Session, project_id: int) -> Project:
    p = db.get(Project, project_id)
    if not p:
        raise HTTPException(404, "项目不存在")
    return p


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    return db.query(Project).order_by(Project.created_at.desc()).all()


@router.post("", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: Session = Depends(get_db)):
    p = Project(**body.model_dump())
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: int, db: Session = Depends(get_db)):
    return get_project_or_404(db, project_id)


@router.put("/{project_id}", response_model=ProjectOut)
def update_project(project_id: int, body: ProjectUpdate,
                   db: Session = Depends(get_db)):
    p = get_project_or_404(db, project_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(p, k, v)
    db.commit()
    db.refresh(p)
    return p


@router.delete("/{project_id}")
def delete_project(project_id: int, db: Session = Depends(get_db)):
    p = get_project_or_404(db, project_id)
    db.query(Claim).filter(Claim.project_id == project_id).delete()
    db.delete(p)
    db.commit()
    return {"ok": True}


@router.get("/{project_id}/stats")
def project_stats(project_id: int, db: Session = Depends(get_db)):
    get_project_or_404(db, project_id)
    q = db.query(Claim).filter(Claim.project_id == project_id)
    total = q.count()
    pending = q.filter(Claim.status == "pending").count()
    registered = q.filter(Claim.status == "registered").count()
    reviewed = q.filter(Claim.status == "reviewed").count()
    total_amount = db.query(Claim).filter(Claim.project_id == project_id)
    sum_claimed = sum(float(c.claim_amount or 0) for c in total_amount.all())
    sum_audited = sum(float(c.audited_amount or 0) for c in total_amount.all())
    return {
        "total": total, "pending": pending, "registered": registered,
        "reviewed": reviewed,
        "sum_claimed": round(sum_claimed, 2),
        "sum_audited": round(sum_audited, 2),
    }
