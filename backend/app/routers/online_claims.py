"""在线申报债权：公开网页提交 → 管理人一键导入台账。"""
import json
import re
import shutil
import threading
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import Claim, ClaimFile, OnlineClaim, OnlineClaimFile, Project
from ..schemas import OnlineClaimOut
from ..services import parser
from ..services import formatter
from .claims import _parse_and_extract, next_claim_no
from .projects import get_project_or_404

router = APIRouter(prefix="/api", tags=["online-claims"])

# 公开申报可提交的字段（与台账字段一一对应）
FIELD_KEYS = [
    "name", "credit_code", "legal_rep", "contact_info", "address",
    "claim_category", "claim_nature", "claim_date",
    "principal", "interest", "others", "claim_amount", "remark",
]
NUM_KEYS = {"principal", "interest", "others", "claim_amount"}

SUPPORTED_EXT = {".pdf", ".doc", ".docx", ".txt", ".png", ".jpg", ".jpeg",
                 ".bmp", ".tif", ".tiff", ".webp"}


def _to_num(v) -> float:
    """表单金额转数字，容错中文单位/千分位。"""
    if v is None:
        return 0.0
    s = str(v).strip().replace(",", "").replace("，", "")
    if not s:
        return 0.0
    if s.endswith("万"):
        try:
            return round(float(s[:-1]) * 10000, 2)
        except ValueError:
            return 0.0
    try:
        return round(float(s), 2)
    except ValueError:
        return 0.0


def _decode_filename(raw: str) -> str:
    name = raw.replace("\\", "/").split("/")[-1]
    if "\ufffd" in name:
        try:
            name = name.encode("latin-1").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def next_submit_no(db: Session, project_id: int) -> str:
    """申报流水号：WS-0001 格式，按项目内递增。"""
    nums = []
    for (no,) in db.query(OnlineClaim.submit_no).filter(
            OnlineClaim.project_id == project_id).all():
        m = re.search(r"(\d+)$", no or "")
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return f"WS-{n:03d}"


def _online_dir(project_id: int, submit_no: str) -> Path:
    return config.UPLOAD_DIR / "online" / str(project_id) / submit_no


# ---------------- 公开提交 ----------------

@router.post("/online-apply", response_model=OnlineClaimOut)
async def online_apply(request: Request,
                       project_id: int = Form(...),
                       name: str = Form(""),
                       credit_code: str = Form(""),
                       legal_rep: str = Form(""),
                       contact_info: str = Form(""),
                       address: str = Form(""),
                       claim_category: str = Form(""),
                       claim_nature: str = Form(""),
                       claim_date: str = Form(""),
                       principal: str = Form(""),
                       interest: str = Form(""),
                       others: str = Form(""),
                       claim_amount: str = Form(""),
                       remark: str = Form(""),
                       files: list[UploadFile] = File(default=[]),
                       db: Session = Depends(get_db)):
    """公开网页提交债权申报（无需登录）。"""
    project = get_project_or_404(db, project_id)
    # 三项必填校验（名称 / 统一社会信用代码或身份证号 / 联系方式）
    if not name.strip():
        raise HTTPException(400, "请填写债权人名称")
    if not credit_code.strip():
        raise HTTPException(400, "请填写统一社会信用代码 / 身份证号码")
    if not contact_info.strip():
        raise HTTPException(400, "请填写联系方式")
    if len(name.strip()) > 200:
        raise HTTPException(400, "债权人名称过长")
    if len(credit_code.strip()) > 100:
        raise HTTPException(400, "统一社会信用代码 / 身份证号码过长")
    if len(contact_info.strip()) > 200:
        raise HTTPException(400, "联系方式过长")

    unsupported = [f.filename for f in files
                   if not parser.is_supported(f.filename or "")]
    if unsupported:
        raise HTTPException(400, f"不支持的文件类型：{'、'.join(unsupported)}")

    submit_no = next_submit_no(db, project_id)
    oc = OnlineClaim(
        project_id=project_id, submit_no=submit_no,
        name=name.strip(),
        credit_code=credit_code.strip(),
        legal_rep=legal_rep.strip(),
        contact_info=contact_info.strip(),
        address=address.strip(),
        claim_category=claim_category.strip(),
        claim_nature=claim_nature.strip(),
        claim_date=formatter.format_date_cn(claim_date),
        principal=_to_num(principal),
        interest=_to_num(interest),
        others=_to_num(others),
        claim_amount=_to_num(claim_amount),
        remark=remark.strip(),
        status="new",
        ip_addr=request.client.host if request.client else "",
    )
    if not oc.claim_amount:
        oc.claim_amount = round(oc.principal + oc.interest + oc.others, 2)
    db.add(oc)
    db.flush()

    # 存储文件（目录：uploads/online/<项目>/<流水号>/）
    oc_dir = _online_dir(project_id, submit_no)
    oc_dir.mkdir(parents=True, exist_ok=True)
    for uf in files:
        raw = _decode_filename(uf.filename or "unnamed")
        stored = f"{uuid.uuid4().hex}_{raw}"
        dest = oc_dir / stored
        with dest.open("wb") as f:
            shutil.copyfileobj(uf.file, f)
        db.add(OnlineClaimFile(
            online_claim_id=oc.id,
            filename=raw, stored_name=stored,
            file_type=parser.classify(raw),
            file_path=str(dest.relative_to(config.UPLOAD_DIR)),
            size=dest.stat().st_size,
        ))

    db.commit()
    db.refresh(oc)
    return oc


# ---------------- 管理人侧 ----------------

@router.get("/projects/{project_id}/online-claims",
            response_model=list[OnlineClaimOut])
def list_online_claims(project_id: int, db: Session = Depends(get_db)):
    """列出项目的在线申报（含文件，按流水号排序）。"""
    get_project_or_404(db, project_id)
    rows = db.query(OnlineClaim).filter(
        OnlineClaim.project_id == project_id).all()
    rows.sort(key=lambda r: [int(x) for x in
                             re.findall(r"\d+", r.submit_no or "0")] or [0])
    return rows


@router.delete("/projects/{project_id}/online-claims/{oid}")
def delete_online_claim(project_id: int, oid: int,
                        db: Session = Depends(get_db)):
    """删除/忽略一条在线申报（含文件）。"""
    oc = db.get(OnlineClaim, oid)
    if not oc or oc.project_id != project_id:
        raise HTTPException(404, "申报记录不存在")
    for rec in oc.files:
        p = config.UPLOAD_DIR / rec.file_path
        if p.exists():
            p.unlink(missing_ok=True)
    db.delete(oc)
    db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/online-claims/import")
def import_online_claims(project_id: int, body: dict,
                         db: Session = Depends(get_db)):
    """一键导入全部「待导入」在线申报到台账。

    - 同名查重：与项目内已有债权人名称比对；
      存在同名且未 force 时返回 409 + 重复名单。
    - 导入内容：台账字段 + 材料文件复制入库 + 异步解析。
    """
    get_project_or_404(db, project_id)
    force = bool(body.get("force"))

    pending = db.query(OnlineClaim).filter(
        OnlineClaim.project_id == project_id,
        OnlineClaim.status == "new").all()
    if not pending:
        raise HTTPException(400, "没有待导入的在线申报")

    # 同名查重
    existing = {c.name.strip() for c in db.query(Claim.name).filter(
        Claim.project_id == project_id).all() if c.name and c.name.strip()}
    dup_names = sorted({oc.name.strip() for oc in pending
                        if oc.name.strip() in existing})
    if dup_names and not force:
        raise HTTPException(
            409,
            json.dumps({"duplicates": dup_names,
                        "msg": "台账已存在同名债权人，请确认是否仍导入"},
                       ensure_ascii=False))

    imported, failed = [], []
    for oc in pending:
        claim_dir = None
        try:
            # 每条独立 savepoint：单条失败回滚不影响其他条
            with db.begin_nested():
                claim_no = next_claim_no(db, project_id)
                claim = Claim(
                    project_id=project_id, claim_no=claim_no,
                    name=oc.name.strip(),
                    credit_code=oc.credit_code.strip(),
                    legal_rep=oc.legal_rep.strip(),
                    contact_info=oc.contact_info.strip(),
                    address=oc.address.strip(),
                    claim_category=oc.claim_category.strip(),
                    claim_nature=oc.claim_nature.strip(),
                    # 日期统一「2025年4月5日」；金额统一数值（显示端千分位）
                    claim_date=formatter.format_date_cn(oc.claim_date),
                    principal=formatter.format_amount(oc.principal),
                    interest=formatter.format_amount(oc.interest),
                    others=formatter.format_amount(oc.others),
                    claim_amount=formatter.format_amount(oc.claim_amount),
                    source_files=json.dumps(
                        [f.filename for f in oc.files], ensure_ascii=False),
                    parse_status="pending",
                )
                db.add(claim)
                db.flush()

                # 复制文件 → 债权目录
                claim_dir = config.UPLOAD_DIR / str(project_id) / claim_no
                claim_dir.mkdir(parents=True, exist_ok=True)
                for rec in oc.files:
                    src = config.UPLOAD_DIR / rec.file_path
                    if not src.exists():
                        continue
                    stored = f"{uuid.uuid4().hex}_{rec.filename}"
                    dest = claim_dir / stored
                    shutil.copy2(src, dest)
                    db.add(ClaimFile(
                        claim_id=claim.id, project_id=project_id,
                        filename=rec.filename, stored_name=stored,
                        file_type=rec.file_type,
                        file_path=str(dest.relative_to(config.UPLOAD_DIR)),
                        size=dest.stat().st_size,
                        ocr_text="", parse_status="pending",
                    ))

                oc.status = "imported"
                oc.imported_claim_id = claim.id
                imported.append({"claim_id": claim.id, "claim_no": claim_no,
                                 "name": claim.name})
        except Exception as e:  # noqa: BLE001
            # 清理失败条目的孤儿文件
            if claim_dir and claim_dir.exists():
                shutil.rmtree(claim_dir, ignore_errors=True)
            failed.append({"submit_no": oc.submit_no, "name": oc.name,
                           "error": str(e)})

    db.commit()
    # 异步解析（OCR + 字段提取自动同步台账）
    for it in imported:
        threading.Thread(target=_parse_and_extract,
                         args=(it["claim_id"],), daemon=True).start()
    return {"ok": True, "imported": imported, "failed": failed}
