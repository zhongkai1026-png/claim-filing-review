"""债权台账 API：上传、解析、CRUD、登记/复核。"""
import json
import re
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import AuditResult, Claim, ClaimFile, Project
from ..schemas import ClaimOut, ClaimUpdate, FileOut
from ..services import extractor, parser
from .projects import get_project_or_404

router = APIRouter(prefix="/api", tags=["claims"])


def get_claim_or_404(db: Session, claim_id: int) -> Claim:
    c = db.get(Claim, claim_id)
    if not c:
        raise HTTPException(404, "债权记录不存在")
    return c


def _decode_filename(raw: str) -> str:
    """文件名容错：部分 Windows 客户端以 GBK 字节上传，解码后会出现乱码，
    检测替换符/异常字符并尝试用 latin-1 字节回退 GBK 解码。"""
    name = raw.replace("\\", "/").split("/")[-1]
    if "\ufffd" in name:
        try:
            name = name.encode("latin-1").decode("gbk")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return name


def next_claim_no(db: Session, project_id: int) -> str:
    """生成债权编号：PC-001 格式，按项目内序号递增。"""
    nums = []
    for (no,) in db.query(Claim.claim_no).filter(
            Claim.project_id == project_id).all():
        m = re.search(r"(\d+)$", no or "")
        if m:
            nums.append(int(m.group(1)))
    n = (max(nums) + 1) if nums else 1
    return f"PC-{n:03d}"


# ---------------- 上传与解析 ----------------

def _save_material_files(db: Session, claim: Claim, files: list[UploadFile],
                         origin: str = "") -> list[ClaimFile]:
    """把上传文件落盘到该债权的材料目录并建立 ClaimFile 记录（不提交事务）。

    origin 为空表示首次申报材料，supplement 表示补充材料。
    """
    claim_dir = config.UPLOAD_DIR / str(claim.project_id) / claim.claim_no
    claim_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for uf in files:
        raw = _decode_filename(uf.filename or "unnamed")
        stored = f"{uuid.uuid4().hex}_{raw}"
        dest = claim_dir / stored
        with dest.open("wb") as f:
            shutil.copyfileobj(uf.file, f)
        rec = ClaimFile(
            claim_id=claim.id, project_id=claim.project_id,
            filename=raw, stored_name=stored,
            file_type=parser.classify(raw),
            file_path=str(dest.relative_to(config.UPLOAD_DIR)),
            size=dest.stat().st_size,
            ocr_text="",
            parse_status="pending",
            origin=origin,
        )
        db.add(rec)
        records.append(rec)
    return records


def _check_supported(files: list[UploadFile]) -> None:
    unsupported = [f.filename for f in files
                   if not parser.is_supported(f.filename or "")]
    if unsupported:
        raise HTTPException(400, f"不支持的文件类型：{'、'.join(unsupported)}")


@router.post("/projects/{project_id}/upload", response_model=ClaimOut)
async def upload_materials(project_id: int,
                           files: list[UploadFile] = File(...),
                           db: Session = Depends(get_db)):
    """上传申报材料：新建债权记录 → 存储文件 → 解析文本 → 提取字段预填。"""
    get_project_or_404(db, project_id)
    if not files:
        raise HTTPException(400, "未选择文件")

    _check_supported(files)

    claim_no = next_claim_no(db, project_id)
    claim = Claim(project_id=project_id, claim_no=claim_no,
                  parse_status="pending")
    db.add(claim)
    db.flush()  # 拿到 claim.id

    file_records = _save_material_files(db, claim, files)

    claim.source_files = json.dumps([r.filename for r in file_records],
                                    ensure_ascii=False)
    db.commit()
    db.refresh(claim)
    # 异步解析（扫描件 PDF 需 OCR，耗时较长，不阻塞上传响应）
    threading.Thread(target=_parse_and_extract, args=(claim.id,),
                     daemon=True).start()
    return claim


@router.post("/claims/{claim_id}/supplement")
async def supplement_materials(claim_id: int,
                               files: list[UploadFile] = File(...),
                               db: Session = Depends(get_db)):
    """补充材料：向已有债权追加材料文件。

    补充后：
    1. 新材料与原有材料同库保存 → 在材料预览中一并显示（带「补充」标识）；
    2. 后台仅解析新增文件（OCR/文本提取），并把提取结果按「只补空、不覆盖」策略同步台账；
    3. 清空 AI 审查结论（回到「未审查」），人工复核标记为未完成，流程状态由「已复核」退回「已登记」，
       以便重新执行 AI 审查与人工复核。
    """
    claim = get_claim_or_404(db, claim_id)
    if not files:
        raise HTTPException(400, "未选择文件")
    _check_supported(files)

    records = _save_material_files(db, claim, files, origin="supplement")

    # 材料清单（来源材料字段）追加新文件名
    try:
        names = json.loads(claim.source_files or "[]")
        if not isinstance(names, list):
            names = []
    except (TypeError, ValueError):
        names = []
    names.extend(r.filename for r in records)
    claim.source_files = json.dumps(names, ensure_ascii=False)

    # ---- 重置 AI 审查结论与流程状态 ----
    prev_status = claim.status
    prev_ai = "none"
    audit = db.query(AuditResult).filter(
        AuditResult.claim_id == claim_id).first()
    if not audit:
        audit = AuditResult(claim_id=claim_id)
        db.add(audit)
    prev_ai = audit.ai_status or "none"
    audit.ai_status = "none"        # 回到「未审查」
    audit.ai_opinion = ""           # 清空旧审查意见（材料已变化，结论失效）
    audit.ai_error = ""
    audit.ai_model = ""
    audit.ai_started_at = None
    # 人工复核：标记未完成（保留原意见文本与审核金额，下次复核表单会自动带出，便于在此基础上修改）
    audit.manual_status = "none"

    # 流程状态：已复核 → 退回已登记（待重新复核）；待登记/已登记保持不变
    if claim.status == "reviewed":
        claim.status = "registered"
    claim.parse_status = "pending"
    db.commit()

    file_ids = [r.id for r in records]
    threading.Thread(target=_parse_and_extract,
                     args=(claim_id,), kwargs={"file_ids": file_ids},
                     daemon=True).start()

    return {
        "ok": True,
        "added": len(records),
        "files": [{"id": r.id, "filename": r.filename,
                   "file_type": r.file_type, "size": r.size,
                   "parse_status": r.parse_status} for r in records],
        "reset": {
            "ai_status_before": prev_ai,
            "status_before": prev_status,
            "status_after": claim.status,
            "manual_status": "none",
        },
        "claim": ClaimOut.model_validate(claim).model_dump(),
    }


def _parse_and_extract(claim_id: int, file_ids: list[int] | None = None) -> None:
    """后台任务：解析材料文件（含 OCR）并提取字段，自动同步到台账。

    file_ids 为 None 时解析该债权的全部材料；补充材料时只传新增文件 id，
    避免重复 OCR 老材料（扫描件单份可能耗时数十秒）。
    """
    from ..database import SessionLocal
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if not claim:
            return
        claim.parse_status = "parsing"
        claim.parse_started_at = datetime.now()
        claim.parse_error = ""
        db.commit()
        for rec in claim.files:
            if file_ids is not None and rec.id not in file_ids:
                continue
            p = config.UPLOAD_DIR / rec.file_path
            if p.exists():
                parsed = parser.parse_file(p, rec.filename)
                rec.ocr_text = parsed["text"]
                rec.parse_status = parsed["parse_status"]
                rec.parse_engine = parsed.get("engine", "")
        db.commit()
        # 字段提取（LLM 优先，规则兜底）：以该债权全部已解析材料为依据
        texts = [(f.ocr_text or "") for f in claim.files
                 if (f.ocr_text or "").strip()]
        # 防覆盖策略：
        #   1) 台账已有申报信息（名称非空 = 云端导入/人工登记过）→ 解析仅补空，
        #      不覆盖已有字段，避免无关材料（如管理人函件）污染申报数据；
        #   2) 金额字段提取值为 0（未识别）→ 不覆盖已有金额。
        extracted = extractor.extract_fields("\n\n".join(texts))
        has_existing = bool((claim.name or "").strip())
        money_keys = ("principal", "interest", "others", "claim_amount",
                      "audited_principal", "audited_interest",
                      "audited_others", "audited_amount")
        for k, v in extracted.items():
            if v in (None, ""):
                continue
            cur = getattr(claim, k, None)
            if k in money_keys:
                try:
                    cur_num = float(cur or 0)
                except (TypeError, ValueError):
                    cur_num = 0.0
                try:
                    num = float(v or 0)
                except (TypeError, ValueError):
                    continue
                if has_existing and cur_num != 0:
                    continue          # 已有金额：不覆盖（避免材料污染申报数据）
                if num <= 0 and has_existing:
                    continue          # 已登记记录：未识别金额（0）不写入
                setattr(claim, k, num)
            else:
                # 文本字段：已有值时不覆盖（补充材料只补空）
                if has_existing and str(cur or "").strip():
                    continue
                setattr(claim, k, v)
        # 总额未识别时按分项求和
        if not (claim.claim_amount or 0) and (claim.principal or 0):
            claim.claim_amount = round(float(claim.principal or 0)
                                       + float(claim.interest or 0)
                                       + float(claim.others or 0), 2)
        claim.parse_status = "done"
        claim.parse_error = ""
        db.commit()
    except Exception as e:  # noqa: BLE001
        import logging
        logging.getLogger(__name__).exception("解析失败")
        try:
            claim = db.get(Claim, claim_id)
            if claim:
                claim.parse_status = "failed"
                claim.parse_error = f"{type(e).__name__}: {e}"[:280]
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


# 解析耗时上限：扫描件走 MinerU 云端时，20MB 级 PDF 可能数分钟；
# 超过该时长仍未结束视为中断（服务重启/线程异常退出），标记失败以便重新解析。
PARSE_TIMEOUT_MIN = 30


def heal_stale_parse(db: Session, claim: Claim) -> Claim:
    """自愈：解析中长期无进展的债权标记为失败并写明原因（避免永久卡在「解析中」）。

    注意：没有材料文件的债权（如 Excel 导入台账的行）不参与自愈——
    它们本来就没有可解析的材料，状态应为 empty。
    """
    if (claim.parse_status or "") not in ("pending", "parsing"):
        return claim
    if not claim.files:
        if claim.parse_status == "pending":
            claim.parse_status = "empty"      # 无材料：无需解析
            db.commit()
        return claim
    started = claim.parse_started_at or claim.created_at
    if not started:
        return claim
    if (datetime.now() - started).total_seconds() < PARSE_TIMEOUT_MIN * 60:
        return claim
    claim.parse_status = "failed"
    claim.parse_error = (f"解析超过 {PARSE_TIMEOUT_MIN} 分钟仍未完成（大文件扫描件耗时较长，"
                         f"或服务重启导致任务中断），请重新解析")
    for rec in claim.files:
        if (rec.parse_status or "") in ("pending", "parsing"):
            rec.parse_status = "failed"
    db.commit()
    return claim


@router.post("/claims/{claim_id}/reparse", response_model=ClaimOut)
def reparse_claim(claim_id: int, db: Session = Depends(get_db)):
    """重新解析材料并刷新提取字段（异步）。

    解析中（且未超时）再次点击会被拒绝，避免重复清空文本、重复触发 OCR。
    """
    claim = get_claim_or_404(db, claim_id)
    claim = heal_stale_parse(db, claim)
    if claim.parse_status == "parsing":
        started = claim.parse_started_at or claim.created_at
        mins = int((datetime.now() - started).total_seconds() // 60) if started else 0
        raise HTTPException(
            409, f"该债权正在解析中（已 {mins} 分钟）。扫描件走云解析可能需要数分钟，"
                 f"请稍候刷新查看；如超过 {PARSE_TIMEOUT_MIN} 分钟仍无结果，系统会自动"
                 f"标记失败，届时可重新解析")
    if not claim.files:
        raise HTTPException(400, "该债权没有材料文件（如从 Excel 导入的台账行），"
                                 "请先用行内「⋯ → 📎 补充材料」上传材料后再解析")
    claim.parse_status = "pending"
    claim.parse_error = ""
    for rec in claim.files:
        rec.ocr_text = ""
        rec.parse_status = "pending"
    db.commit()
    threading.Thread(target=_parse_and_extract, args=(claim_id,),
                     daemon=True).start()
    db.refresh(claim)
    return claim


# ---------------- 台账查询与编辑 ----------------

@router.get("/claims", response_model=list[ClaimOut])
def list_claims(project_id: int | None = None, keyword: str = "",
                status: str = "", claim_category: str = "",
                db: Session = Depends(get_db)):
    q = db.query(Claim)
    if project_id:
        q = q.filter(Claim.project_id == project_id)
    if keyword:
        like = f"%{keyword}%"
        q = q.filter(Claim.name.like(like) | Claim.claim_no.like(like)
                     | Claim.credit_code.like(like))
    if status:
        q = q.filter(Claim.status == status)
    if claim_category:
        q = q.filter(Claim.claim_category == claim_category)
    return q.order_by(Claim.claim_no.asc()).all()


@router.get("/claims/{claim_id}", response_model=ClaimOut)
def get_claim(claim_id: int, db: Session = Depends(get_db)):
    return heal_stale_parse(db, get_claim_or_404(db, claim_id))


@router.post("/claims/batch-delete")
def batch_delete_claims(body: dict, db: Session = Depends(get_db)):
    """批量删除债权（含材料文件与审查记录）。"""
    ids = [int(i) for i in (body.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "未选择要删除的债权")
    deleted = 0
    for cid in ids:
        claim = db.get(Claim, cid)
        if not claim:
            continue
        for rec in list(claim.files):
            p = config.UPLOAD_DIR / rec.file_path
            if p.exists():
                p.unlink(missing_ok=True)
        # 用 ORM 删除子表，避免 bulk delete 与会话中已加载对象冲突
        # （旧写法会出现 "expected to delete N row(s); 0 were matched" 并留下孤儿行）
        for rec in list(claim.files):
            db.delete(rec)
        for ar in db.query(AuditResult).filter(
                AuditResult.claim_id == cid).all():
            db.delete(ar)
        db.delete(claim)
        deleted += 1
    db.commit()
    return {"ok": True, "deleted": deleted}


@router.get("/claims/{claim_id}/detail")
def get_claim_detail(claim_id: int, db: Session = Depends(get_db)):
    """详情：台账 + 文件列表 + 审查结果（顺带自愈卡死的解析状态）。"""
    claim = heal_stale_parse(db, get_claim_or_404(db, claim_id))
    files = db.query(ClaimFile).filter(ClaimFile.claim_id == claim_id).all()
    audit = db.query(AuditResult).filter(
        AuditResult.claim_id == claim_id).first()
    return {
        "claim": ClaimOut.model_validate(claim).model_dump(),
        "files": [FileOut.model_validate(f).model_dump() for f in files],
        "audit": (audit.__dict__.copy() if audit else None),
    }


@router.put("/claims/{claim_id}", response_model=ClaimOut)
def update_claim(claim_id: int, body: ClaimUpdate,
                 db: Session = Depends(get_db)):
    """保存初审/编辑。

    - 总额自动汇总：申报总额＝申报本金＋利息＋其他；审核总额＝审核本金＋利息＋其他；
    - 保存后若仍是「待登记」且已填债权人名称，则自动登记为「已登记」。
    """
    claim = get_claim_or_404(db, claim_id)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(claim, k, v)

    def _sum3(pk: str, ik: str, ok_: str) -> float:
        return round(float(getattr(claim, pk) or 0)
                     + float(getattr(claim, ik) or 0)
                     + float(getattr(claim, ok_) or 0), 2)

    # 分项被改动 → 重新汇总总额（分项全为 0 且原有总额时保留原总额，避免误清零）
    if any(k in data for k in ("principal", "interest", "others")):
        total = _sum3("principal", "interest", "others")
        if total or not float(claim.claim_amount or 0):
            claim.claim_amount = total
    if any(k in data for k in ("audited_principal", "audited_interest",
                               "audited_others")):
        total = _sum3("audited_principal", "audited_interest", "audited_others")
        if total or not float(claim.audited_amount or 0):
            claim.audited_amount = total

    # 初审/编辑保存后自动登记（债权人名称为空则仍保持待登记）
    auto_registered = False
    if claim.status == "pending" and (claim.name or "").strip():
        claim.status = "registered"
        auto_registered = True
    # 记录人工确认时间：此后 AI 审查以台账数据为优先依据（材料文本仅用于核验）
    claim.verified_at = datetime.now()
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/claims/{claim_id}/unregister", response_model=ClaimOut)
def unregister_claim(claim_id: int, db: Session = Depends(get_db)):
    """取消登记：已登记 / 已复核 → 待登记（保留材料文件与审查、复核记录）。"""
    claim = get_claim_or_404(db, claim_id)
    if claim.status == "pending":
        raise HTTPException(400, "该债权已是「待登记」状态")
    claim.status = "pending"
    db.commit()
    db.refresh(claim)
    return claim


@router.delete("/claims/{claim_id}")
def delete_claim(claim_id: int, db: Session = Depends(get_db)):
    claim = get_claim_or_404(db, claim_id)
    # 删除文件（先删磁盘文件，再用 ORM 删子表行，避免残留孤儿行）
    for rec in list(claim.files):
        p = config.UPLOAD_DIR / rec.file_path
        if p.exists():
            p.unlink(missing_ok=True)
    for rec in list(claim.files):
        db.delete(rec)
    for ar in db.query(AuditResult).filter(
            AuditResult.claim_id == claim_id).all():
        db.delete(ar)
    db.delete(claim)
    db.commit()
    return {"ok": True}


# ---------------- 登记 / 复核 流程 ----------------

@router.post("/claims/{claim_id}/register", response_model=ClaimOut)
def register_claim(claim_id: int, db: Session = Depends(get_db)):
    """标记登记完成（要求债权人名称必填）。"""
    claim = get_claim_or_404(db, claim_id)
    if not claim.name.strip():
        raise HTTPException(400, "债权人名称为必填项，请先完善登记信息")
    claim.status = "registered"
    db.commit()
    db.refresh(claim)
    return claim


@router.post("/claims/{claim_id}/review", response_model=ClaimOut)
def review_claim(claim_id: int, body: ClaimUpdate,
                 db: Session = Depends(get_db)):
    """人工复核：保存审核金额并标记已复核。"""
    claim = get_claim_or_404(db, claim_id)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(claim, k, v)
    if body.audited_amount is None:
        claim.audited_amount = round(float(claim.audited_principal or 0)
                                     + float(claim.audited_interest or 0)
                                     + float(claim.audited_others or 0), 2)
    claim.status = "reviewed"
    db.commit()
    db.refresh(claim)
    return claim
