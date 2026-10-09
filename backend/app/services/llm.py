"""LLM 客户端：OpenAI 兼容接口（默认 DeepSeek）。

模型配置存于数据库 ai_configs 表（系统内「AI 设置」管理，可添加/切换）；
未配置任何激活模型时，所有函数返回 None，调用方降级到规则引擎。
"""
import json
import logging

import httpx

from .. import config

logger = logging.getLogger(__name__)

# 最近一次调用失败原因（供上层写入错误提示）
_last_error = ""


def get_last_error() -> str:
    return _last_error


def _set_error(msg: str) -> None:
    global _last_error
    _last_error = msg


def get_active_config() -> dict | None:
    """读取当前激活的 AI 配置（数据库 ai_configs 表 is_active=1）。"""
    from ..database import SessionLocal
    from ..models import AIConfig

    db = SessionLocal()
    try:
        cfg = db.query(AIConfig).filter(AIConfig.is_active == 1).first()
        if not cfg or not cfg.api_key.strip():
            return None
        return {
            "name": cfg.name,
            "base_url": (cfg.base_url or "").rstrip("/"),
            "api_key": cfg.api_key,
            "model": cfg.model,
        }
    except Exception as e:  # noqa: BLE001
        logger.warning("读取 AI 配置失败: %s", e)
        return None
    finally:
        db.close()


def chat(messages: list, json_mode: bool = False, temperature: float = 0.2,
         max_tokens: int = config.AI_MAX_TOKENS) -> str | None:
    """调用 chat/completions，返回回复文本；失败返回 None。"""
    cfg = get_active_config()
    if not cfg:
        return None
    payload = {
        "model": cfg["model"],
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        payload["response_format"] = {"type": "json_object"}
    try:
        resp = httpx.post(
            f"{cfg['base_url']}/chat/completions",
            headers={"Authorization": f"Bearer {cfg['api_key']}"},
            json=payload,
            timeout=config.AI_TIMEOUT,
        )
        if resp.status_code != 200:
            # 记录服务端返回的具体错误（模型不存在 / Key 无效 / 限流等）
            detail = ""
            try:
                j = resp.json()
                detail = (j.get("error") or {}).get("message") or str(j)[:200]
            except Exception:  # noqa: BLE001
                detail = resp.text[:200]
            _set_error(f"HTTP {resp.status_code}：{detail}")
            logger.warning("LLM 调用失败: HTTP %s %s", resp.status_code, detail)
            return None
        data = resp.json()
        choice = (data.get("choices") or [{}])[0] or {}
        finish = choice.get("finish_reason") or ""
        message = choice.get("message") or {}
        content = message.get("content")
        # 部分网关把正文拆成 parts 数组返回
        if isinstance(content, list):
            content = "".join(
                (p.get("text") or "") if isinstance(p, dict) else str(p)
                for p in content)
        content = content or ""
        reasoning = message.get("reasoning_content") or ""

        if not content.strip():
            # 思考型模型（reasoning）的思考过程与正文共用 max_tokens 额度：
            # 思考吃满额度时正文为空、finish_reason=length，需与「模型名错误」区分开
            if finish == "length":
                _set_error(
                    f"生成被 max_tokens={max_tokens} 截断：本次思考（reasoning）已占用全部额度，"
                    f"正文为空。请调大 AI_MAX_TOKENS（当前 {config.AI_MAX_TOKENS}）"
                    f"或改用非思考模型（如 deepseek-chat）")
            elif reasoning.strip():
                _set_error(
                    f"模型只返回了思考内容（reasoning_content），未给出正文"
                    f"（finish_reason={finish or '空'}）；请调大 max_tokens 或改用非思考模型")
            else:
                _set_error(
                    f"模型返回内容为空（finish_reason={finish or '空'}，模型={cfg.get('model')}）；"
                    f"请检查模型名是否正确、该模型在网关侧是否可用或余额是否充足")
            logger.warning("LLM 返回空内容，模型=%s finish=%s 思考长度=%s",
                           cfg.get("model"), finish, len(reasoning))
            return None
        if finish == "length":
            logger.warning("LLM 输出被 max_tokens=%s 截断，模型=%s（JSON 可能不完整）",
                           max_tokens, cfg.get("model"))
        _set_error("")
        return content
    except Exception as e:  # noqa: BLE001
        _set_error(f"{type(e).__name__}: {e}")
        logger.warning("LLM 调用失败: %s", e)
        return None


def chat_json(messages: list, temperature: float = 0.1,
              max_tokens: int = config.AI_MAX_TOKENS) -> dict | None:
    """请求 JSON 结构化输出，返回 dict；失败返回 None。"""
    text = chat(messages, json_mode=True, temperature=temperature,
                max_tokens=max_tokens)
    if not text:
        return None
    # 容错：剥离可能存在的 markdown 代码围栏
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # 记录具体原因，避免上层拿到上一次调用残留/空的错误信息
        _set_error("模型返回内容不是合法 JSON（常见原因：输出被 max_tokens 截断，"
                   "请调大 AI_MAX_TOKENS 后重试）")
        logger.warning("LLM 返回非 JSON: %s", text[:200])
        return None
