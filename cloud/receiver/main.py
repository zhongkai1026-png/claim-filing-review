# -*- coding: utf-8 -*-
"""
债权申报接收服务（阿里云暂存端）
================================
职责：接收债权人从公网申报页提交的申报数据与材料，校验后暂存到本地目录，
并提供带管理员令牌的保护接口供管理人本地工具拉取（列表 / 打包下载 / 确认 / 删除）。

数据流向：申报页(浏览器) → POST /api/apply → 暂存 data/cloud/{申报号}/ → 本地工具拉取 → 导入 SQLite
"""
import json
import re
import shutil
import uuid
import zipfile
from collections import defaultdict, deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import config

app = FastAPI(title="债权申报接收服务", docs_url=None, redoc_url=None, openapi_url=None)

# 允许跨域（申报页与接收服务可能不同源；管理接口靠令牌鉴权，不受跨域影响）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def no_cache_html(request: Request, call_next):
    """申报页（HTML）不缓存：更新页面后债权人刷新即可见新版。

    不设该头时浏览器会按启发式规则缓存（旧页面可能被缓存一两天不复验），
    导致「云端页面已更新、但访问者仍看到旧版」。仅作用于 text/html，
    模板下载与接口响应不受影响；仍保留 ETag，未变更时走 304，几乎不增加流量。
    """
    resp = await call_next(request)
    ctype = resp.headers.get("content-type", "")
    if ctype.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp

SUBMIT_DIR = config.DATA_DIR / "cloud"
SUBMIT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------- 工具函数
_hits = defaultdict(deque)  # ip -> [时间戳...]


def rate_limited(ip: str) -> bool:
    """单 IP 频率限制，超过返回 True（拒绝）"""
    now = datetime.now().timestamp()
    q = _hits[ip]
    while q and now - q[0] > config.RATE_WINDOW_SEC:
        q.popleft()
    if len(q) >= config.RATE_LIMIT:
        return True
    q.append(now)
    return False


def safe_name(name: str) -> str:
    """存储文件名：去路径 + 字符白名单 + 随机前缀（防路径穿越/重名）"""
    base = Path(name or "").name
    base = re.sub(r"[^\w.\-\u4e00-\u9fff()（） ]", "_", base)
    base = (base or "file")[:80]
    return f"{uuid.uuid4().hex[:8]}-{base}"


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def new_submit_no() -> str:
    d = datetime.now()
    return f"C-{d:%Y%m%d}-{d:%H%M%S}-{uuid.uuid4().hex[:4].upper()}"


def _check_token(authorization: str | None, token_param: str | None) -> None:
    tok = ""
    if authorization and authorization.lower().startswith("bearer "):
        tok = authorization[7:].strip()
    elif token_param:
        tok = token_param.strip()
    if not tok or tok != config.ADMIN_TOKEN:
        raise HTTPException(401, "管理员令牌无效")


def _load_manifest(d: Path) -> dict | None:
    mf = d / "manifest.json"
    if not mf.exists():
        return None
    try:
        return json.loads(mf.read_text(encoding="utf-8"))
    except Exception:
        return None


# ---------------------------------------------------------------- 债权人提交
@app.post("/api/apply")
async def apply_claim(
    request: Request,
    project: str = Form(""),
    name: str = Form(""),
    credit_code: str = Form(""),
    legal_rep: str = Form(""),
    contact: str = Form(""),
    email: str = Form(""),
    address: str = Form(""),
    agent_name: str = Form(""),
    agent_id: str = Form(""),
    agent_phone: str = Form(""),
    claim_category: str = Form(""),
    claim_nature: str = Form(""),
    claim_date: str = Form(""),
    apply_date: str = Form(""),
    guarantee: str = Form(""),
    litigation: str = Form("否"),
    principal: str = Form("0"),
    interest: str = Form("0"),
    others: str = Form("0"),
    claim_amount: str = Form("0"),
    remark: str = Form(""),
    extra_json: str = Form(""),
    files: list[UploadFile] = File(default_factory=list),
):
    ip = request.client.host if request.client else "unknown"

    # 1. 限流
    if rate_limited(ip):
        raise HTTPException(429, "提交过于频繁，请稍后再试")

    # 2. 项目码 + 必填字段
    if project not in config.PROJECT_CODES:
        raise HTTPException(400, "项目码无效，请联系管理人获取正确链接")
    name = name.strip()
    credit_code = credit_code.strip()
    contact = contact.strip()
    if not name or len(name) > 120:
        raise HTTPException(400, "债权人名称缺失或过长")
    if not credit_code or len(credit_code) > 30:
        raise HTTPException(400, "统一社会信用代码/身份证号缺失或过长")
    if not contact or len(contact) > 30:
        raise HTTPException(400, "联系方式缺失或过长")
    try:
        amount = round(float(claim_amount or 0), 2)
        if amount <= 0:
            raise ValueError
    except ValueError:
        raise HTTPException(400, "申报总额无效")
    if len(remark) > 2000:
        raise HTTPException(400, "补充说明过长")
    if len(files) > config.MAX_FILES:
        raise HTTPException(400, f"材料最多 {config.MAX_FILES} 个文件")

    # 3. 建目录、写文件（出错即清理，不留半成品）
    no = new_submit_no()
    claim_dir = SUBMIT_DIR / no
    file_dir = claim_dir / "files"
    file_dir.mkdir(parents=True, exist_ok=True)
    manifest_files, total = [], 0
    try:
        for uf in files:
            ext = Path(uf.filename or "").suffix.lower()
            if ext not in config.ALLOWED_EXT:
                raise HTTPException(400, f"不支持的文件类型：{uf.filename}")
            data = await uf.read()
            if not data:
                continue
            if len(data) > config.MAX_FILE_MB * 1024 * 1024:
                raise HTTPException(400, f"文件过大：{uf.filename}（上限 {config.MAX_FILE_MB}MB）")
            total += len(data)
            if total > config.MAX_TOTAL_MB * 1024 * 1024:
                raise HTTPException(400, f"材料总大小超过 {config.MAX_TOTAL_MB}MB")
            stored = safe_name(uf.filename or "file")
            (file_dir / stored).write_bytes(data)
            manifest_files.append({
                "name": uf.filename or stored, "size": len(data),
                "type": uf.content_type or "", "stored": f"files/{stored}",
            })
    except HTTPException:
        shutil.rmtree(claim_dir, ignore_errors=True)
        raise

    # 4. 写 manifest.json
    extra = {}
    if extra_json:
        try:
            parsed = json.loads(extra_json[:4000])
            if isinstance(parsed, dict):
                extra = parsed
        except Exception:
            extra = {}
    manifest = {
        "submit_no": no,
        "submitted_at": now_str(),
        "project": project,
        "client_ip": ip,
        "creditor": {
            "name": name, "credit_code": credit_code,
            "legal_rep": legal_rep.strip()[:60], "contact": contact,
            "email": email.strip()[:80], "address": address.strip()[:200],
        },
        "agent": {
            "name": agent_name.strip()[:60],
            "id_no": agent_id.strip()[:30],
            "phone": agent_phone.strip()[:30],
        },
        "claim": {
            "category": claim_category, "nature": claim_nature,
            "date": claim_date, "apply_date": apply_date,
            "guarantee": guarantee, "litigation": litigation,
            "principal": principal, "interest": interest, "others": others,
            "amount": str(amount), "remark": remark.strip()[:2000],
        },
        "files": manifest_files,
        "extra": extra,
        "status": "pending",
    }
    (claim_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return JSONResponse({"ok": True, "submit_no": no, "project": project})


# ---------------------------------------------------------------- 管理端
@app.get("/api/health")
def health():
    return {"ok": True, "service": "claim-receiver", "time": now_str()}


@app.get("/api/admin/claims")
def admin_list(
    authorization: str | None = Header(default=None),
    token: str | None = None,
    status: str | None = None,
):
    """列出暂存申报（可带 ?status=pending 过滤）"""
    _check_token(authorization, token)
    rows = []
    for d in sorted(SUBMIT_DIR.iterdir()):
        if not d.is_dir():
            continue
        m = _load_manifest(d)
        if not m:
            continue
        rows.append({
            "submit_no": m.get("submit_no"),
            "submitted_at": m.get("submitted_at"),
            "project": m.get("project"),
            "status": m.get("status", "pending"),
            "creditor": m.get("creditor", {}).get("name", ""),
            "amount": m.get("claim", {}).get("amount", ""),
            "file_count": len(m.get("files", [])),
            "files": [f.get("name") for f in m.get("files", [])],
        })
    rows.sort(key=lambda x: x.get("submitted_at") or "", reverse=True)
    if status:
        rows = [r for r in rows if r.get("status") == status]
    return {"total": len(rows), "claims": rows}


@app.get("/api/admin/claims/{no}/package")
def admin_package(no: str, authorization: str | None = Header(default=None), token: str | None = None):
    """打包下载某条申报（manifest.json + 全部材料，ZIP）"""
    _check_token(authorization, token)
    d = SUBMIT_DIR / no
    if not (d / "manifest.json").exists():
        raise HTTPException(404, "申报不存在")
    zpath = config.DATA_DIR / f"{no}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(d / "manifest.json", "manifest.json")
        fdir = d / "files"
        if fdir.is_dir():
            for f in sorted(fdir.iterdir()):
                z.write(f, f"files/{f.name}")
    return FileResponse(zpath, filename=f"{no}-申报材料包.zip", media_type="application/zip")


@app.post("/api/admin/claims/{no}/ack")
def admin_ack(no: str, authorization: str | None = Header(default=None), token: str | None = None):
    """标记已导入本地台账（防重复拉取）"""
    _check_token(authorization, token)
    mf = SUBMIT_DIR / no / "manifest.json"
    if not mf.exists():
        raise HTTPException(404, "申报不存在")
    m = json.loads(mf.read_text(encoding="utf-8"))
    m["status"] = "imported"
    m["ack_at"] = now_str()
    mf.write_text(json.dumps(m, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "submit_no": no, "status": "imported"}


@app.delete("/api/admin/claims/{no}")
def admin_delete(no: str, authorization: str | None = Header(default=None), token: str | None = None):
    """删除某条暂存申报（确认导入后清理）"""
    _check_token(authorization, token)
    d = SUBMIT_DIR / no
    if not d.exists():
        raise HTTPException(404, "申报不存在")
    shutil.rmtree(d, ignore_errors=True)
    (config.DATA_DIR / f"{no}.zip").unlink(missing_ok=True)
    return {"ok": True, "submit_no": no}


# ---------------------------------------------------------------- 静态申报页（兜底路由，放在最后）
STATIC_DIR = config.STATIC_DIR
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
