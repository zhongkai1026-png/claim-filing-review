"""MinerU Open API 客户端：云端文档解析（扫描件/图片/表格识别更强）。

流程：申请上传链接 → PUT 上传（自动触发解析）→ 轮询批量结果 → 下载 zip 取 full.md。
未配置 MINERU_API_KEY 或调用失败时由调用方回退本地 OCR。
"""
import io
import logging
import time
import zipfile
from pathlib import Path

import httpx

from .. import config

logger = logging.getLogger(__name__)

API_BASE = "https://mineru.net/api/v4"
MINERU_API_KEY = config.MINERU_API_KEY
MINERU_TIMEOUT = config.MINERU_TIMEOUT
MINERU_POLL_SEC = config.MINERU_POLL_SEC
MINERU_POLL_MAX = config.MINERU_POLL_MAX  # 最多轮询次数


def is_configured() -> bool:
    return bool(MINERU_API_KEY.strip())


def _headers() -> dict:
    return {"Authorization": f"Bearer {MINERU_API_KEY.strip()}"}


def parse_file(path: Path, filename: str) -> str:
    """用 MinerU 解析一个文件，返回 Markdown 文本；失败返回空串。"""
    if not is_configured():
        return ""
    headers = _headers()
    try:
        # 1. 申请上传链接
        r = httpx.post(
            f"{API_BASE}/file-urls/batch",
            headers={**headers, "Content-Type": "application/json"},
            json={"files": [{"name": filename, "is_ocr": True}],
                  "model_version": "vlm"},
            timeout=MINERU_TIMEOUT,
        )
        r.raise_for_status()
        j = r.json()
        if j.get("code") != 0:
            logger.warning("MinerU 申请链接失败: %s", j.get("msg"))
            return ""
        batch_id = j["data"]["batch_id"]
        upload_url = (j["data"].get("file_urls") or [None])[0]
        if not upload_url:
            return ""

        # 2. PUT 上传（自动触发解析）
        with path.open("rb") as f:
            r2 = httpx.put(upload_url, content=f.read(), timeout=MINERU_TIMEOUT)
        if r2.status_code != 200:
            logger.warning("MinerU 上传失败: HTTP %s", r2.status_code)
            return ""

        # 3. 轮询批量结果
        for _ in range(MINERU_POLL_MAX):
            time.sleep(MINERU_POLL_SEC)
            r3 = httpx.get(f"{API_BASE}/extract-results/batch/{batch_id}",
                           headers=headers, timeout=MINERU_TIMEOUT)
            r3.raise_for_status()
            j3 = r3.json()
            if j3.get("code") != 0:
                continue
            results = j3.get("data", {}).get("extract_result") or []
            for item in results:
                state = item.get("state")
                if state == "done":
                    return _download_md(item.get("full_zip_url"))
                if state == "failed":
                    logger.warning("MinerU 解析失败: %s", item.get("err_msg"))
                    return ""
        logger.warning("MinerU 轮询超时")
        return ""
    except Exception as e:  # noqa: BLE001
        logger.warning("MinerU 调用异常: %s", e)
        return ""


def _download_md(zip_url: str) -> str:
    """下载解析结果 zip，提取 full.md 文本；HTML 表格转管道分隔纯文本。"""
    if not zip_url:
        return ""
    try:
        r = httpx.get(zip_url, timeout=MINERU_TIMEOUT)
        r.raise_for_status()
        z = zipfile.ZipFile(io.BytesIO(r.content))
        for name in z.namelist():
            if name.endswith(".md"):
                text = z.read(name).decode("utf-8", "ignore")
                return _table_to_text(text)
    except Exception as e:  # noqa: BLE001
        logger.warning("MinerU 结果下载失败: %s", e)
    return ""


def _table_to_text(text: str) -> str:
    """把 MinerU 输出的 HTML 表格转为「| 单元格 |」纯文本，便于字段提取正则。"""
    import re
    text = re.sub(r"<tr[^>]*>", "\n", text)
    text = re.sub(r"<td[^>]*>", " | ", text)
    text = re.sub(r"<th[^>]*>", " | ", text)
    text = re.sub(r"</t[dh]>", " | ", text)
    text = re.sub(r"</tr>", "\n", text)
    text = re.sub(r"</?table[^>]*>", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" \| ", " | ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()
