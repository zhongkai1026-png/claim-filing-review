"""AI 模型配置管理：系统内添加/编辑/切换多个 OpenAI 兼容模型。"""
import logging

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import AIConfig
from ..schemas import AIConfigIn, AIConfigOut

router = APIRouter(prefix="/api/ai-configs", tags=["ai-configs"])

logger = logging.getLogger(__name__)


def _to_out(cfg: AIConfig) -> dict:
    return AIConfigOut(
        id=cfg.id, name=cfg.name, base_url=cfg.base_url,
        api_key=cfg.api_key, model=cfg.model,
        is_active=bool(cfg.is_active),
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    ).model_dump()


@router.get("", response_model=list[AIConfigOut])
def list_configs(db: Session = Depends(get_db)):
    """列出所有 AI 模型配置（激活的排最前）。"""
    rows = db.query(AIConfig).order_by(AIConfig.is_active.desc(),
                                       AIConfig.id.asc()).all()
    return [_to_out(r) for r in rows]


@router.post("", response_model=AIConfigOut)
def create_config(body: AIConfigIn, db: Session = Depends(get_db)):
    """新增配置；若为第一条或指定激活，则设为当前激活。"""
    if not body.name.strip():
        raise HTTPException(400, "请填写配置名称")
    if not body.api_key.strip():
        raise HTTPException(400, "请填写 API Key")

    has_any = db.query(AIConfig).count() > 0
    activate = body.activate or not has_any
    if activate:
        db.query(AIConfig).update({AIConfig.is_active: 0})

    cfg = AIConfig(
        name=body.name.strip(),
        base_url=(body.base_url or "").strip().rstrip("/"),
        api_key=body.api_key.strip(),
        model=(body.model or "").strip(),
        is_active=1 if activate else 0,
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return _to_out(cfg)


@router.put("/{cfg_id}", response_model=AIConfigOut)
def update_config(cfg_id: int, body: AIConfigIn,
                  db: Session = Depends(get_db)):
    """编辑配置（不改激活状态）。"""
    cfg = db.get(AIConfig, cfg_id)
    if not cfg:
        raise HTTPException(404, "配置不存在")
    cfg.name = body.name.strip() or cfg.name
    cfg.base_url = (body.base_url or "").strip().rstrip("/")
    if body.api_key:
        cfg.api_key = body.api_key.strip()
    cfg.model = (body.model or "").strip()
    if body.activate:
        db.query(AIConfig).update({AIConfig.is_active: 0})
        cfg.is_active = 1
    db.commit()
    db.refresh(cfg)
    return _to_out(cfg)


@router.post("/{cfg_id}/activate", response_model=AIConfigOut)
def activate_config(cfg_id: int, db: Session = Depends(get_db)):
    """切换激活：只有一条配置保持 is_active=1。"""
    cfg = db.get(AIConfig, cfg_id)
    if not cfg:
        raise HTTPException(404, "配置不存在")
    db.query(AIConfig).update({AIConfig.is_active: 0})
    cfg.is_active = 1
    db.commit()
    db.refresh(cfg)
    return _to_out(cfg)


@router.delete("/{cfg_id}")
def delete_config(cfg_id: int, db: Session = Depends(get_db)):
    """删除配置；若删的是激活项，则激活剩余第一条。"""
    cfg = db.get(AIConfig, cfg_id)
    if not cfg:
        raise HTTPException(404, "配置不存在")
    was_active = bool(cfg.is_active)
    db.delete(cfg)
    db.commit()
    if was_active:
        rest = db.query(AIConfig).order_by(AIConfig.id.asc()).first()
        if rest:
            rest.is_active = 1
            db.commit()
    return {"ok": True}


@router.post("/test")
def test_config(body: AIConfigIn):
    """测试连接：用给定参数发一条最小请求，返回耗时/错误。"""
    if not body.api_key.strip():
        raise HTTPException(400, "请填写 API Key")
    base = (body.base_url or "").strip().rstrip("/")
    model = (body.model or "").strip()
    if not base:
        raise HTTPException(400, "请填写接口地址")
    if not model:
        raise HTTPException(400, "请填写模型名")
    import time
    t0 = time.time()
    try:
        resp = httpx.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {body.api_key.strip()}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 5,
            },
            timeout=config.AI_TIMEOUT,
        )
        cost = round(time.time() - t0, 2)
        if resp.status_code == 200:
            return {"ok": True, "message": f"连接成功，耗时 {cost}s",
                    "model": model}
        detail = ""
        try:
            detail = resp.json().get("error", {}).get("message", "")
        except Exception:  # noqa: BLE001
            pass
        return {"ok": False,
                "message": f"HTTP {resp.status_code}：{detail or resp.text[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "message": f"连接失败：{e}"}
