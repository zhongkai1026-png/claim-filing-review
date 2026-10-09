"""台账导入 API：Excel 导入（按系统导出台账模板）。"""
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from ..database import get_db
from ..services import importer
from .projects import get_project_or_404

router = APIRouter(prefix="/api", tags=["import"])


@router.post("/import/ledger")
async def import_ledger(project_id: int,
                        file: UploadFile = File(...),
                        db: Session = Depends(get_db)):
    """导入台账 Excel（.xlsx，系统导出格式），按表头字段同步到指定项目。"""
    get_project_or_404(db, project_id)
    fname = (file.filename or "").lower()
    if not fname.endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "仅支持 .xlsx / .xlsm 格式的 Excel 文件")
    data = await file.read()
    if not data:
        raise HTTPException(400, "文件内容为空")
    result = importer.import_ledger_excel(data, project_id, db)
    return result


@router.get("/import/template")
def download_template(project_id: int, db: Session = Depends(get_db)):
    """下载空白导入模板（仅表头含序号，无数据内容）。"""
    from fastapi.responses import Response
    from ..services import exporter
    from .export import _content_disposition

    project = get_project_or_404(db, project_id)
    data = exporter.export_template(project)
    fname = f"台账导入模板_{project.name}.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": _content_disposition(fname)})
