"""导出服务：Excel 台账、Word 审查意见书、批量打包 zip。"""
import io
import json
import zipfile
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .. import config
from ..models import AuditResult, Claim, ClaimFile, Project

# 台账导出列（key -> 中文表头）
LEDGER_COLUMNS = [
    ("seq", "序号"),
    ("claim_no", "债权编号"),
    ("name", "债权人名称"),
    ("credit_code", "统一社会信用代码/身份证号码"),
    ("legal_rep", "法定代表人/负责人"),
    ("contact_info", "联系方式"),
    ("address", "联系地址"),
    ("agent_name", "代理人姓名"),
    ("agent_id_no", "代理人身份证号"),
    ("agent_contact", "代理人联系方式"),
    ("agent_address", "代理人地址"),
    ("account_name", "开户名称"),
    ("bank_name", "开户行"),
    ("account_no", "账号"),
    ("claim_category", "债权种类"),
    ("litigation_status", "涉诉涉执情况"),
    ("claim_nature", "申报债权性质"),
    ("claim_date", "申报债权时间"),
    ("principal", "申报本金"),
    ("interest", "申报利息"),
    ("others", "申报其他"),
    ("claim_amount", "申报总额"),
    ("audited_principal", "审核本金"),
    ("audited_interest", "审核利息"),
    ("audited_others", "审核其他"),
    ("audited_amount", "审核总额"),
    ("debt_nature", "债权性质"),
    ("guarantee_notes", "担保情况备注"),
    ("claim_type", "债权类型"),
    ("status", "状态"),
    ("source_files", "来源材料"),
    ("created_at", "创建时间"),
]

# 导出/模板列宽（含序号列）
COLUMN_WIDTHS = [8, 12, 22, 24, 14, 18, 26, 14, 20, 18, 26, 16, 16, 20,
                 12, 12, 16, 16, 14, 14, 14, 14, 14, 14, 14, 14,
                 14, 26, 14, 10, 30, 18]

# 金额列（导出时写数值并设千分位格式）
MONEY_KEYS = {"principal", "interest", "others", "claim_amount",
              "audited_principal", "audited_interest",
              "audited_others", "audited_amount"}


def _money_text(v) -> str:
    """金额文本（千分位，整数省略小数位）：2000000 → 2,000,000。"""
    from .formatter import format_amount_text
    return format_amount_text(v)


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.2f}"
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M")
    return str(v)


def export_ledger(project: Project, claims: list[Claim]) -> bytes:
    """生成 Excel 台账（xlsx bytes）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "债权申报台账"

    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # 标题行
    ws.merge_cells(start_row=1, start_column=1, end_row=1,
                   end_column=len(LEDGER_COLUMNS))
    title_cell = ws.cell(row=1, column=1,
                         value=f"{project.name} 债权申报台账（导出时间：{datetime.now():%Y-%m-%d %H:%M}）")
    title_cell.font = Font(bold=True, size=14)
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 28

    # 表头
    for col, (_, header) in enumerate(LEDGER_COLUMNS, start=1):
        c = ws.cell(row=2, column=col, value=header)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
        c.border = border
    ws.row_dimensions[2].height = 32

    # 数据
    for r, claim in enumerate(claims, start=3):
        files = [f.filename for f in claim.files]
        values = {
            "seq": r - 2,
            "claim_no": claim.claim_no,
            "name": claim.name,
            "credit_code": claim.credit_code,
            "legal_rep": claim.legal_rep,
            "contact_info": claim.contact_info,
            "address": claim.address,
            "agent_name": claim.agent_name,
            "agent_id_no": claim.agent_id_no,
            "agent_contact": claim.agent_contact,
            "agent_address": claim.agent_address,
            "account_name": claim.account_name,
            "bank_name": claim.bank_name,
            "account_no": claim.account_no,
            "claim_category": claim.claim_category,
            "litigation_status": claim.litigation_status,
            "claim_nature": claim.claim_nature,
            "claim_date": claim.claim_date,
            "principal": float(claim.principal or 0),
            "interest": float(claim.interest or 0),
            "others": float(claim.others or 0),
            "claim_amount": float(claim.claim_amount or 0),
            "audited_principal": float(claim.audited_principal or 0),
            "audited_interest": float(claim.audited_interest or 0),
            "audited_others": float(claim.audited_others or 0),
            "audited_amount": float(claim.audited_amount or 0),
            "debt_nature": claim.debt_nature,
            "guarantee_notes": claim.guarantee_notes,
            "claim_type": claim.claim_type,
            "status": {"pending": "待登记", "registered": "已登记",
                       "reviewed": "已复核"}.get(claim.status, claim.status),
            "source_files": "；".join(files),
            "created_at": _fmt(claim.created_at),
        }
        for col, (key, _) in enumerate(LEDGER_COLUMNS, start=1):
            val = values.get(key, "")
            c = ws.cell(row=r, column=col, value=val)
            # 金额列：数值 + 千分位格式（2,000,000；有小数时显示 2 位）
            if key in MONEY_KEYS:
                c.number_format = "#,##0.##"
                c.alignment = Alignment(vertical="center", horizontal="right")
            else:
                c.alignment = Alignment(vertical="center", wrap_text=True)
            c.border = border

    # 列宽
    for i, w in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A3"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_template(project: Project) -> bytes:
    """生成空白导入模板：仅表头（含序号列），无任何数据内容。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "债权申报台账模板"

    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    # 第 1 行即表头（含序号列）
    for col, (_, header) in enumerate(LEDGER_COLUMNS, start=1):
        c = ws.cell(row=1, column=col, value=header)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal="center", vertical="center",
                                wrap_text=True)
        c.border = border
    ws.row_dimensions[1].height = 32

    # 预留若干空行并加边框，方便直接填写（无任何内容）
    for r in range(2, 22):
        for col in range(1, len(LEDGER_COLUMNS) + 1):
            ws.cell(row=r, column=col).border = border

    for i, w in enumerate(COLUMN_WIDTHS, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _set_run(run, name_cn: str = "仿宋_GB2312", size: int = 14,
             bold: bool = False):
    """设置中文字体（西文用 Times New Roman）。"""
    from docx.shared import Pt
    from docx.oxml.ns import qn
    run.font.name = "Times New Roman"
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name_cn)
    run.font.size = Pt(size)
    run.bold = bold


def _add_table(doc, headers: list, rows: list[list], widths=None):
    """生成居中表格（Table Grid 样式）。"""
    from docx.enum.table import WD_TABLE_ALIGNMENT
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    table = doc.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for j, h in enumerate(headers):
        cell = table.rows[0].cells[j]
        cell.text = ""
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        _set_run(p.add_run(h), name_cn="黑体", size=12, bold=True)
    for row in rows:
        cells = table.add_row().cells
        for j, v in enumerate(row):
            cells[j].text = ""
            p = cells[j].paragraphs[0]
            _set_run(p.add_run(str(v or "—")), size=12)
    if widths:
        for j, w in enumerate(widths):
            for row in table.rows:
                row.cells[j].width = w
    return table


def _load_draft(result: AuditResult | None) -> dict:
    """读取人工编辑稿（opinion_draft JSON）；无则返回空 dict。"""
    if result and result.opinion_draft:
        try:
            d = json.loads(result.opinion_draft)
            if isinstance(d, dict):
                return d
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def _opinion_text(claim: Claim, result: AuditResult | None,
                  draft: dict | None = None) -> dict:
    """计算意见书可编辑文本块（编辑稿优先，否则 AI 意见/规则生成）。

    返回：{checks: 四类勾选行, reason: 意见说明, material_evidence: 列表,
          diff_reason: 差额原因, legal_basis: 列表}
    """
    ai = None
    if result and result.ai_opinion:
        try:
            ai = json.loads(result.ai_opinion)
        except json.JSONDecodeError:
            ai = None
    review_result = (ai or {}).get("review_result", "") or "partial"
    claimed = float(claim.claim_amount or 0)
    audited = float(claim.audited_amount or 0)

    if review_result == "rejected":
        checks = ["□ 全部确认", "□ 部分确认，其余不予确认", "□ 暂缓认定",
                  "☑ 全部不予确认"]
        reason = "原因：" + ((ai or {}).get("summary") or "主体不适格/超时效/证据不足未补正/虚假债权")
    elif review_result == "partial":
        checks = ["□ 全部确认", "□ 部分确认，其余不予确认", "☑ 暂缓认定",
                  "□ 全部不予确认"]
        reason = "暂缓原因：" + ((ai or {}).get("summary") or "涉诉涉裁待决/证据需补充/附条件未成就")
    elif audited > 0 and audited < claimed - 0.01:
        checks = ["□ 全部确认", "☑ 部分确认，其余不予确认", "□ 暂缓认定",
                  "□ 全部不予确认"]
        reason = "差额理由：" + ((ai or {}).get("amount_review") or "部分申报缺乏证据支持，不予确认")
    else:
        checks = ["☑ 全部确认", "□ 部分确认，其余不予确认", "□ 暂缓认定",
                  "□ 全部不予确认"]
        reason = "确认理由：" + ((ai or {}).get("summary") or "事实清楚、证据充分、法律关系明确、时效有效")

    material_ev = (ai or {}).get("material_evidence") or []
    legal_basis = (ai or {}).get("legal_basis") or []
    if not legal_basis:
        legal_basis = ["《企业破产法》第46条第2款：附利息的债权自破产受理时起停止计息",
                       "《企业破产法》第58条：债权异议与确认程序"]

    if draft:
        if isinstance(draft.get("checks"), list) and len(draft["checks"]) == 4:
            checks = [str(c) for c in draft["checks"]]
        if draft.get("reason"):
            reason = str(draft["reason"])
        if isinstance(draft.get("material_evidence"), list):
            material_ev = [str(x) for x in draft["material_evidence"] if str(x).strip()]
        if draft.get("diff_reason"):
            pass  # 差额原因并入 reason，见下方 reason 段
        if isinstance(draft.get("legal_basis"), list):
            legal_basis = [str(x) for x in draft["legal_basis"] if str(x).strip()]

    diff_reason = reason
    for pre in ("差额理由：", "确认理由：", "暂缓原因：", "原因："):
        if diff_reason.startswith(pre):
            diff_reason = diff_reason[len(pre):]
            break
    return {"checks": checks, "reason": reason,
            "material_evidence": material_ev,
            "diff_reason": diff_reason, "legal_basis": legal_basis}


def _opinion_doc(project: Project, claim: Claim, result: AuditResult | None,
                 file_names: list[str]) -> bytes:
    """生成《破产债权审查结果通知书》Word（公文格式）。

    结构：标题/文号/致/引言 → 申报情况表 → 审查结果表 → 四类结论勾选
          → 差额说明表 → 法律依据 → 权利告知 → 落款
    （不输出内部审查过程/决策树）
    """
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    from docx.oxml.ns import qn

    doc = Document()
    # 页边距：上2.54 / 下2.54 / 左3.0 / 右2.6 cm
    sec = doc.sections[0]
    sec.top_margin = Cm(2.54)
    sec.bottom_margin = Cm(2.54)
    sec.left_margin = Cm(3.0)
    sec.right_margin = Cm(2.6)

    style = doc.styles["Normal"]
    style.font.name = "Times New Roman"
    style.font.size = Pt(14)
    rpr = style.element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), "仿宋_GB2312")

    # 标题：黑体 22pt 居中
    h = doc.add_paragraph()
    h.alignment = WD_ALIGN_PARAGRAPH.CENTER
    h.paragraph_format.space_after = Pt(6)
    _set_run(h.add_run("破产债权审查结果通知书"), name_cn="黑体", size=22, bold=True)

    # 文号：右对齐
    year = datetime.now().year
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_run(p.add_run(f"〔{year}〕破管债审字第 {claim.id:03d} 号"), size=12)

    # 可编辑文本块（编辑稿优先）
    draft = _load_draft(result)
    txt = _opinion_text(claim, result, draft)

    # 致 + 引言
    doc.add_paragraph()
    doc.add_paragraph(f"致：{claim.name or '（债权人名称待补）'}")
    intro = (f"在{project.debtor or '【债务人】'}破产一案中，贵方于"
             f"{claim.claim_date or '【日期】'}向管理人申报债权。经管理人审查，"
             f"现将审查结果通知如下：")
    doc.add_paragraph(intro)

    # 一、申报情况
    doc.add_paragraph("一、申报情况")
    _add_table(doc,
               ["债权性质", "申报本金(元)", "申报利息(元)", "申报其他(元)", "申报总额(元)"],
               [[claim.claim_nature or "—", _money_text(claim.principal),
                 _money_text(claim.interest), _money_text(claim.others),
                 _money_text(claim.claim_amount)]])
    doc.add_paragraph()

    # 二、审查结果
    doc.add_paragraph("二、审查结果")
    _add_table(doc,
               ["确认债权性质", "确认本金(元)", "确认利息(元)", "确认其他(元)", "确认总额(元)"],
               [[claim.debt_nature or claim.claim_nature or "—",
                 _money_text(claim.audited_principal), _money_text(claim.audited_interest),
                 _money_text(claim.audited_others), _money_text(claim.audited_amount)]])
    doc.add_paragraph()

    # 三、审查意见说明（四类勾选）
    doc.add_paragraph("三、审查意见说明")
    for c in txt["checks"]:
        doc.add_paragraph(c)
    doc.add_paragraph(txt["reason"])

    # 材料关键证据
    if txt["material_evidence"]:
        doc.add_paragraph("材料关键证据：")
        for e in txt["material_evidence"]:
            doc.add_paragraph(f"　• {e}")
        doc.add_paragraph()

    # 四、差额说明
    claimed = float(claim.claim_amount or 0)
    audited = float(claim.audited_amount or 0)
    doc.add_paragraph("四、差额说明")
    _add_table(doc, ["申报总额(元)", "确认总额(元)", "差额(元)", "原因"],
               [[_money_text(claimed), _money_text(audited),
                 _money_text(claimed - audited),
                 txt["diff_reason"]]])
    doc.add_paragraph()

    # 五、法律依据
    doc.add_paragraph("五、法律依据")
    for b in txt["legal_basis"]:
        doc.add_paragraph(b)
    doc.add_paragraph()

    # 六、权利告知
    doc.add_paragraph("六、权利告知")
    doc.add_paragraph("1. 贵方如对本审查结果有异议，应自收到本通知书之日起15日内，"
                      "向管理人提交书面异议及相应证据；")
    doc.add_paragraph("2. 管理人将对异议进行复核，并出具《债权复核结果通知书》；")
    doc.add_paragraph("3. 贵方对复核结果仍有异议的，可依法向受理破产申请的人民法院提起诉讼"
                      "（《企业破产法》第58条）。")
    doc.add_paragraph()

    # 落款（右对齐）
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_run(p.add_run(f"管理人：{project.manager or '（管理人全称）'}"
                       f"{'（管理人印章）' if project.manager else ''}"))
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    _set_run(p.add_run(f"日期：{datetime.now():%Y年%m月%d日}"))

    p = doc.add_paragraph()
    _set_run(p.add_run("说明：本通知书由 AI 辅助初审生成，经管理人复核后生效。"),
             name_cn="楷体", size=12)

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def opinion_preview_data(project: Project, claim: Claim,
                         result: AuditResult | None) -> dict:
    """意见书预览/编辑数据：固定表格数据 + 可编辑文本块（含当前编辑稿）。"""
    draft = _load_draft(result)
    txt = _opinion_text(claim, result, draft)
    ai = None
    if result and result.ai_opinion:
        try:
            ai = json.loads(result.ai_opinion)
        except json.JSONDecodeError:
            ai = None
    return {
        "claim_no": claim.claim_no,
        "name": claim.name or "",
        "claim_nature": claim.claim_nature or "",
        "principal": float(claim.principal or 0),
        "interest": float(claim.interest or 0),
        "others": float(claim.others or 0),
        "claim_amount": float(claim.claim_amount or 0),
        "debt_nature": claim.debt_nature or claim.claim_nature or "",
        "audited_principal": float(claim.audited_principal or 0),
        "audited_interest": float(claim.audited_interest or 0),
        "audited_others": float(claim.audited_others or 0),
        "audited_amount": float(claim.audited_amount or 0),
        "checks": txt["checks"],
        "reason": txt["reason"],
        "material_evidence": txt["material_evidence"],
        "diff_reason": txt["diff_reason"],
        "legal_basis": txt["legal_basis"],
        "has_draft": bool(draft),
        "review_result": (ai or {}).get("review_result", ""),
        "conclusion": (ai or {}).get("conclusion", ""),
    }


def export_opinion(project: Project, claim: Claim) -> bytes:
    """导出单份审查意见书 Word。"""
    result = None
    ar = claim.audit_results
    if ar:
        result = ar[0]
    file_names = [f.filename for f in claim.files]
    return _opinion_doc(project, claim, result, file_names)


def export_opinions_zip(project: Project, claims: list[Claim]) -> bytes:
    """批量导出审查意见书，打包 zip。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for claim in claims:
            result = claim.audit_results[0] if claim.audit_results else None
            file_names = [f.filename for f in claim.files]
            data = _opinion_doc(project, claim, result, file_names)
            safe_no = claim.claim_no.replace("/", "-").replace("\\", "-")
            zf.writestr(f"审查意见书_{safe_no}.docx", data)
    return buf.getvalue()
