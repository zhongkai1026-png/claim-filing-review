"""文档解析服务：从申报材料中抽取文本。

- PDF：pdfplumber（文本型）+ PyMuPDF（扫描件/混合型兜底）
- Word：python-docx
- 图片 / 扫描件 PDF：RapidOCR（onnxruntime 版 PaddleOCR 模型，本地推理）
"""
import io
import re
from pathlib import Path

# 允许的扩展名 -> 文件类型
ALLOWED_EXT = {
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".txt": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".bmp": "image",
    ".tif": "image",
    ".tiff": "image",
    ".webp": "image",
}

_ocr_engine = None


def _get_ocr():
    """惰性加载 OCR 引擎（全局单例）。"""
    global _ocr_engine
    if _ocr_engine is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_engine = RapidOCR()
        except Exception as e:  # noqa: BLE001
            _ocr_engine = False
            print(f"[parser] OCR 引擎加载失败: {e}")
    return _ocr_engine or None


def classify(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return ALLOWED_EXT.get(ext, "other")


def is_supported(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXT


def parse_file(path: Path, filename: str) -> dict:
    """解析单个文件，返回 {text, parse_status, file_type, engine}。

    PDF（含文本型）与图片一律优先走 MinerU 云端解析（表格/公式还原更强），
    未配置 Key 或调用失败时自动回退本地提取 / RapidOCR。
    engine: "mineru" 云端 / "local" 本地 / "" 无文本
    """
    file_type = classify(filename)
    text = ""
    engine = ""
    status = "done"
    try:
        if file_type == "pdf":
            text, engine = _parse_pdf(path)
        elif file_type == "word":
            text = _parse_word(path)
            engine = "local" if text.strip() else ""
        elif file_type == "text":
            text = _parse_text(path)
            engine = "local" if text.strip() else ""
        elif file_type == "image":
            text, engine = _parse_image(path)
        else:
            status = "empty"
    except Exception as e:  # noqa: BLE001
        text = ""
        status = "failed"
        return {"text": text, "parse_status": status, "file_type": file_type,
                "engine": "", "error": str(e)}

    if status == "done" and not text.strip():
        status = "empty"
    return {"text": text, "parse_status": status, "file_type": file_type,
            "engine": engine, "error": ""}


def _parse_image(path: Path) -> tuple:
    """图片：MinerU 云端优先，回退本地 OCR。返回 (text, engine)。"""
    from . import mineru
    if mineru.is_configured():
        t = mineru.parse_file(path, path.name)
        if t.strip():
            return t, "mineru"
    t = ocr_image(path)
    return t, ("local" if t.strip() else "")


def _parse_pdf(path: Path) -> tuple:
    """PDF：一律优先 MinerU 云端解析，失败回退本地。返回 (text, engine)。"""
    # 1) MinerU 云端解析（文本型/扫描件通吃，表格公式还原更强）
    from . import mineru
    if mineru.is_configured():
        t = mineru.parse_file(path, path.name)
        if t.strip():
            return t, "mineru"
    # 2) 本地回退：文本型 PDF
    parts = []
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                t = page.extract_text() or ""
                parts.append(t)
        if any(p.strip() for p in parts):
            return "\n".join(parts), "local"
    except Exception:
        pass
    # 3) 本地回退：PyMuPDF（扫描页内嵌文本层）
    try:
        import fitz
        doc = fitz.open(path)
        for page in doc:
            parts.append(page.get_text())
        doc.close()
        if any(p.strip() for p in parts):
            return "\n".join(parts), "local"
    except Exception:
        pass
    # 4) 本地回退：扫描件页渲染 OCR
    t = _ocr_pdf_pages(path)
    return t, ("local" if t.strip() else "")


def _ocr_pdf_pages(path: Path) -> str:
    """将 PDF 每页渲染为高分辨率图片并 OCR。"""
    if not _get_ocr():
        return ""
    try:
        import fitz
        doc = fitz.open(path)
        texts = []
        for page in doc:
            # 200 DPI 渲染（zoom 200/72）
            mat = fitz.Matrix(200 / 72, 200 / 72)
            pix = page.get_pixmap(matrix=mat)
            img_bytes = pix.tobytes("png")
            t = _run_ocr_bytes(img_bytes)
            if t.strip():
                texts.append(f"【第{page.number + 1}页】\n{t}")
        doc.close()
        return "\n\n".join(texts)
    except Exception as e:  # noqa: BLE001
        print(f"[parser] PDF OCR 失败: {e}")
        return ""


def _run_ocr_bytes(img_bytes: bytes) -> str:
    engine = _get_ocr()
    if not engine:
        return ""
    try:
        result, _ = engine(img_bytes)
        if not result:
            return ""
        lines = []
        for item in result:
            # item: [box, (text, score), ...]
            if len(item) >= 2:
                txt = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                lines.append(txt)
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        print(f"[parser] OCR 识别失败: {e}")
        return ""


def _parse_word(path: Path) -> str:
    # .docx 直接解析；.doc 老格式尝试 textract 不可用时返回提示
    if path.suffix.lower() == ".docx":
        from docx import Document
        doc = Document(path)
        parts = [p.text for p in doc.paragraphs]
        for table in doc.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text for cell in row.cells))
        return "\n".join(parts)
    return ""  # .doc 老格式：提示转存为 .docx


def _parse_text(path: Path) -> str:
    for enc in ("utf-8", "gbk", "utf-16"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return path.read_text(errors="ignore")


# ---- OCR 引擎（RapidOCR，本地推理）----

def ocr_image(path: Path) -> str:
    """识别图片中的中文文本。"""
    if not _get_ocr():
        return ""
    try:
        engine = _get_ocr()
        result, _ = engine(str(path))
        if not result:
            return ""
        lines = []
        for item in result:
            if len(item) >= 2:
                txt = item[1][0] if isinstance(item[1], (list, tuple)) else str(item[1])
                lines.append(txt)
        return "\n".join(lines)
    except Exception as e:  # noqa: BLE001
        print(f"[parser] 图片 OCR 失败: {e}")
        return ""


def clean_text(text: str, max_len: int = 6000) -> str:
    """清洗文本：压缩空白、截断到模型上下文长度。"""
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:max_len]
