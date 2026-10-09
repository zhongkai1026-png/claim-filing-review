"""申报材料文件：预览 / 下载。"""
import mimetypes

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import ClaimFile

router = APIRouter(prefix="/api/files", tags=["files"])


def get_file_or_404(db: Session, file_id: int) -> ClaimFile:
    f = db.get(ClaimFile, file_id)
    if not f:
        raise HTTPException(404, "文件不存在")
    return f


def _media_type(f: ClaimFile) -> str:
    """按扩展名推断 MIME（pdf/image/text 等）。"""
    if f.file_type == "text":
        return "text/plain; charset=utf-8"
    return mimetypes.guess_type(f.filename)[0] or "application/octet-stream"


@router.get("/{file_id}/preview")
def preview_file(file_id: int, db: Session = Depends(get_db)):
    """内联预览（浏览器直接打开，不触发下载）。"""
    f = get_file_or_404(db, file_id)
    path = config.UPLOAD_DIR / f.file_path
    if not path.exists():
        raise HTTPException(404, "文件已丢失")
    return FileResponse(path, media_type=_media_type(f), filename=f.filename,
                        content_disposition_type="inline")


@router.get("/{file_id}/download")
def download_file(file_id: int, db: Session = Depends(get_db)):
    """下载（附件形式）。"""
    f = get_file_or_404(db, file_id)
    path = config.UPLOAD_DIR / f.file_path
    if not path.exists():
        raise HTTPException(404, "文件已丢失")
    return FileResponse(path, media_type=_media_type(f), filename=f.filename,
                        content_disposition_type="attachment")


@router.get("/{file_id}/text")
def file_text(file_id: int, db: Session = Depends(get_db)):
    """查看文件解析出的文本。"""
    f = get_file_or_404(db, file_id)
    return {"id": f.id, "filename": f.filename, "text": f.ocr_text,
            "parse_status": f.parse_status}
