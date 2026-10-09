"""云端申报同步：从阿里云接收服务拉取申报 → 写入在线申报表（待一键导入台账）。

数据流：申报页(阿里云) → 接收服务暂存 data/cloud/{C-xxx}/ → 本模块拉取 →
       online_claims 表(status=new) → 复用「更新在线申报」导入台账（编号/材料/OCR/查重）。
"""
import io
import json
import uuid
import zipfile
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import CloudConfig, OnlineClaim, OnlineClaimFile, Project
from ..services import formatter, parser
from .online_claims import _decode_filename, _online_dir, _to_num, next_submit_no
from .projects import get_project_or_404

router = APIRouter(prefix="/api", tags=["cloud-sync"])


# ---------------------------------------------------------------- 配置
def _get_config(db: Session) -> CloudConfig:
    cfg = db.get(CloudConfig, 1)
    if not cfg:
        cfg = CloudConfig(id=1)
        db.add(cfg)
        db.commit()
        db.refresh(cfg)
    return cfg


def _mask(tok: str) -> str:
    if not tok:
        return ""
    return (tok[:4] + "****" + tok[-4:]) if len(tok) > 8 else "****"


@router.get("/cloud-sync/config")
def cloud_sync_config(db: Session = Depends(get_db)):
    cfg = _get_config(db)
    return {
        "cloud_url": cfg.cloud_url,
        "admin_token": _mask(cfg.admin_token),
        "token_set": bool(cfg.admin_token),
        "project_id": cfg.project_id,
        "last_sync_at": cfg.last_sync_at.isoformat() if cfg.last_sync_at else None,
    }


@router.put("/cloud-sync/config")
def cloud_sync_save_config(body: dict, db: Session = Depends(get_db)):
    cfg = _get_config(db)
    url = str(body.get("cloud_url") or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        raise HTTPException(400, "云端地址需以 http(s):// 开头")
    if url:
        cfg.cloud_url = url
    if body.get("admin_token"):
        cfg.admin_token = str(body["admin_token"]).strip()
    pid = body.get("project_id")
    if pid:
        get_project_or_404(db, int(pid))
        cfg.project_id = int(pid)
    db.commit()
    return {"ok": True}


@router.post("/cloud-sync/test")
def cloud_sync_test(body: dict, db: Session = Depends(get_db)):
    """测试与云端接收服务的连通性（health + 令牌）。"""
    cfg = _get_config(db)
    url = str(body.get("cloud_url") or "").strip().rstrip("/") or cfg.cloud_url
    token = str(body.get("admin_token") or "").strip() or cfg.admin_token
    if not url:
        raise HTTPException(400, "请先填写云端地址")
    try:
        httpx.get(f"{url}/api/health", timeout=8).raise_for_status()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "step": "health", "error": f"无法连接云端：{e}"}
    if not token:
        return {"ok": False, "step": "token", "error": "未配置管理员令牌"}
    try:
        r = httpx.get(f"{url}/api/admin/claims",
                      headers={"Authorization": f"Bearer {token}"}, timeout=8)
        if r.status_code == 401:
            return {"ok": False, "step": "token", "error": "管理员令牌无效（401）"}
        r.raise_for_status()
        return {"ok": True, "pending": r.json().get("total", 0)}
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "step": "list", "error": f"拉取列表失败：{e}"}


# ---------------------------------------------------------------- 拉取
def _cloud_get(url: str, token: str, path: str) -> httpx.Response:
    resp = httpx.get(f"{url}{path}",
                     headers={"Authorization": f"Bearer {token}"}, timeout=120)
    if resp.status_code == 401:
        raise HTTPException(401, "云端管理员令牌无效")
    resp.raise_for_status()
    return resp


def _cloud_post(url: str, token: str, path: str) -> httpx.Response:
    resp = httpx.post(f"{url}{path}",
                      headers={"Authorization": f"Bearer {token}"}, timeout=60)
    if resp.status_code == 401:
        raise HTTPException(401, "云端管理员令牌无效")
    resp.raise_for_status()
    return resp


def _extra_remark(m: dict) -> str:
    """把云端暂存里台账没有的字段并入 remark，避免信息丢失。"""
    parts = []
    case = m.get("case") or {}
    if case.get("caseNo"):
        parts.append(f"案号：{case['caseNo']}")
    if case.get("debtor"):
        parts.append(f"债务人：{case['debtor']}")
    if case.get("manager"):
        parts.append(f"管理人：{case['manager']}")
    claim = m.get("claim") or {}
    if claim.get("guarantee"):
        parts.append(f"担保情况：{claim['guarantee']}")
    if claim.get("litigation") and claim["litigation"] != "否":
        parts.append(f"涉诉/仲裁：{claim['litigation']}")
    if claim.get("apply_date"):
        parts.append(f"申报日期：{claim['apply_date']}")
    agent = m.get("agent") or {}
    if agent.get("name"):
        ag = f"代理人：{agent['name']}"
        if agent.get("id_no"):
            ag += f"（{agent['id_no']}）"
        if agent.get("phone"):
            ag += f" 电话{agent['phone']}"
        parts.append(ag)
    creditor = m.get("creditor") or {}
    if creditor.get("email"):
        parts.append(f"邮箱：{creditor['email']}")
    extra = m.get("extra") or {}
    eclaim = extra.get("claim") or {}
    if eclaim.get("last_claim_date"):
        parts.append(f"最后一次主张时间：{eclaim['last_claim_date']}")
    if eclaim.get("joint_creditor") == "是":
        parts.append(f"属于连带债权人：是（{eclaim.get('joint_creditor_name') or '未填写名称'}）")
    if eclaim.get("joint_debtor") == "是":
        parts.append(f"有连带债务人：是（{eclaim.get('joint_debtor_name') or '未填写名称'}）")
    if eclaim.get("collateral"):
        parts.append(f"担保物明细及登记情况：{eclaim['collateral']}")
    esvc = extra.get("service") or {}
    svc_parts = []
    if esvc.get("address"):
        svc_parts.append(esvc["address"])
    if esvc.get("recipient"):
        svc_parts.append("收件人 " + esvc["recipient"])
    if esvc.get("phone"):
        svc_parts.append("电话 " + esvc["phone"])
    if esvc.get("email"):
        svc_parts.append("邮箱 " + esvc["email"])
    if esvc.get("wechat"):
        svc_parts.append("微信 " + esvc["wechat"])
    if svc_parts:
        parts.append("送达地址确认：" + "；".join(svc_parts))
    ebank = extra.get("bank") or {}
    if ebank.get("account_name") or ebank.get("account_no"):
        parts.append(f"收款账户：{ebank.get('account_name') or ''} "
                     f"{ebank.get('account_no') or ''}（开户行：{ebank.get('branch') or ''}）")
    base = (claim.get("remark") or "").strip()
    if parts:
        base = (base + "\n" if base else "") + "云端申报补充：" + "；".join(parts)
    return base


def _import_one(db: Session, cfg: CloudConfig, project_id: int, no: str) -> OnlineClaim:
    """下载一条云端申报包 → 写入 online_claims（幂等：调用方按 cloud_claim_id 去重）。"""
    r = _cloud_get(cfg.cloud_url, cfg.admin_token, f"/api/admin/claims/{no}/package")
    with zipfile.ZipFile(io.BytesIO(r.content)) as z:
        manifest = json.loads(z.read("manifest.json").decode("utf-8"))
        file_bytes = {}
        for name in z.namelist():
            if name.startswith("files/"):
                file_bytes[name[len("files/"):]] = z.read(name)

    c = manifest.get("creditor") or {}
    cl = manifest.get("claim") or {}
    ws = next_submit_no(db, project_id)
    oc = OnlineClaim(
        project_id=project_id, submit_no=ws,
        name=str(c.get("name") or "").strip()[:200],
        credit_code=str(c.get("credit_code") or "").strip()[:100],
        legal_rep=str(c.get("legal_rep") or "").strip()[:100],
        contact_info=str(c.get("contact") or "").strip()[:200],
        address=str(c.get("address") or "").strip()[:300],
        claim_category=str(cl.get("category") or "").strip()[:50],
        claim_nature=str(cl.get("nature") or "").strip()[:50],
        claim_date=formatter.format_date_cn(cl.get("date")),
        principal=formatter.format_amount(cl.get("principal")),
        interest=formatter.format_amount(cl.get("interest")),
        others=formatter.format_amount(cl.get("others")),
        claim_amount=formatter.format_amount(cl.get("amount")),
        remark=_extra_remark(manifest),
        status="new",
        ip_addr="cloud",
        cloud_claim_id=no,
        cloud_pulled_at=datetime.now(),
    )
    db.add(oc)
    db.flush()

    oc_dir = _online_dir(project_id, ws)
    oc_dir.mkdir(parents=True, exist_ok=True)
    for raw_name, data in file_bytes.items():
        raw = _decode_filename(raw_name)
        stored = f"{uuid.uuid4().hex}_{raw}"
        (oc_dir / stored).write_bytes(data)
        db.add(OnlineClaimFile(
            online_claim_id=oc.id, filename=raw, stored_name=stored,
            file_type=parser.classify(raw),
            file_path=str((oc_dir / stored).relative_to(config.UPLOAD_DIR)),
            size=len(data),
        ))
    return oc


def _pull_once(db: Session, cfg: CloudConfig, project_id: int):
    if not cfg.cloud_url or not cfg.admin_token:
        raise HTTPException(400, "尚未配置云端地址/令牌，请先保存配置")
    get_project_or_404(db, project_id)

    r = _cloud_get(cfg.cloud_url, cfg.admin_token, "/api/admin/claims?status=pending")
    rows = r.json().get("claims", [])

    # 分流：本地项目 cloud_code ↔ 云端项目码 自动匹配；未绑定的申报兜底进 project_id
    code2pid = {}
    for pid_, code_ in db.query(Project.id, Project.cloud_code).filter(
            Project.cloud_code != "").all():
        if code_:
            code2pid[code_.strip()] = pid_

    pulled, skipped, errors = [], 0, []
    for row in rows:
        no = row.get("submit_no")
        if not no:
            continue
        if db.query(OnlineClaim).filter(OnlineClaim.cloud_claim_id == no).first():
            skipped += 1
            continue
        cloud_code = (row.get("project") or "").strip()
        target_pid = code2pid.get(cloud_code, project_id)  # 未绑定则进默认目标项目
        try:
            oc = _import_one(db, cfg, target_pid, no)
            pulled.append({"submit_no": no, "name": oc.name,
                           "amount": float(oc.claim_amount or 0),
                           "project_id": target_pid,
                           "project_code": cloud_code})
            # 云端确认已拉取（失败不阻断本地入库，可下次再补 ack）
            try:
                _cloud_post(cfg.cloud_url, cfg.admin_token,
                            f"/api/admin/claims/{no}/ack").raise_for_status()
            except Exception:  # noqa: BLE001
                pass
        except Exception as e:  # noqa: BLE001
            errors.append({"submit_no": no, "error": str(e)})

    cfg.last_sync_at = datetime.now()
    db.commit()
    return {"ok": True, "pulled": pulled, "skipped": skipped, "errors": errors}


@router.post("/cloud-sync/pull")
def cloud_sync_pull(body: dict, db: Session = Depends(get_db)):
    """拉取云端待处理申报 → 写入在线申报表（新记录 status=new，等待一键导入台账）。"""
    cfg = _get_config(db)
    pid = int(body.get("project_id") or cfg.project_id or 0)
    if not pid:
        raise HTTPException(400, "请指定目标项目（project_id）")
    return _pull_once(db, cfg, pid)


@router.post("/cloud-sync/pull-and-import")
def cloud_sync_pull_and_import(body: dict, db: Session = Depends(get_db)):
    """拉取云端申报并直接导入台账（等同「拉取」+「更新在线申报」）。

    分流后的申报按各自项目分别导入（多案件并存时互不混淆）。
    """
    from .online_claims import import_online_claims

    cfg = _get_config(db)
    pid = int(body.get("project_id") or cfg.project_id or 0)
    if not pid:
        raise HTTPException(400, "请指定目标项目（project_id）")
    pull = _pull_once(db, cfg, pid)
    if pull["errors"] and not pull["pulled"]:
        return pull

    force = bool(body.get("force"))
    # 导入范围 = 所有有待导入(status=new)申报的项目（覆盖本次拉取 + 历史遗留待导入）
    pids = sorted({r[0] for r in db.query(OnlineClaim.project_id).filter(
        OnlineClaim.status == "new").all()})
    # 每个项目用独立会话导入，避免 SQLite 在同一会话连续写事务时报 database is locked
    from ..database import SessionLocal
    imported, failed, dup = [], [], []
    for rpid in pids:
        s2 = SessionLocal()
        try:
            imp = import_online_claims(rpid, {"force": force}, s2)
            imported += imp.get("imported", [])
            failed += imp.get("failed", [])
        except HTTPException as e:
            if e.status_code == 409:
                dup.append(rpid)
            else:
                raise
        finally:
            s2.close()
    if dup and not force:
        raise HTTPException(
            409,
            json.dumps({"duplicates": [], "msg": "台账存在同名债权人，请确认是否仍导入",
                        "project_ids": dup}, ensure_ascii=False))
    return {"pull": pull, "import": {"imported": imported, "failed": failed}}
