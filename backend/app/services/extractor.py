"""字段提取：从申报材料文本中识别债权人字段。

策略：LLM 结构化提取优先（配置了 API Key 时），失败/未配置时用正则规则兜底。
"""
import json
import re

from .. import config
from . import llm

# 提取目标字段（与台账字段对应）
TARGET_FIELDS = [
    "name", "credit_code", "legal_rep", "contact_info", "address",
    "agent_name", "agent_id_no", "agent_contact", "agent_address",
    "account_name", "bank_name", "account_no",
    "claim_category", "litigation_status", "claim_nature", "claim_date",
    "principal", "interest", "others", "claim_amount",
    "claim_type", "debt_nature", "guarantee_notes",
]

EXTRACT_PROMPT = """你是一名破产管理人助理，负责从债权人申报材料文本中提取结构化信息。
请从下面的申报材料文本中提取债权申报信息，只输出 JSON，不要输出任何其他文字。

输出 JSON 必须只包含以下键（没有的信息给空字符串，金额给数字，无法判断的金额字段给 0）：
{fields}

提取纪律：
- **日期一律照抄材料原文**（含年份），禁止改写年份、禁止使用当前日期或今天作为申报日期；
  材料里没有日期就留空字符串，不要推测。
- 金额照抄材料数字，不要四舍五入或换算（"46.27771万"请换算为 462777.1，但不要臆造）。
- 无法从材料判断的字段留空，不要用常识补全。

申报材料文本：
---
{text}
---"""

# 日期字符串：2020年8月18日 / 2020-08-18 / 2020.8.18
_DATE_RE = re.compile(r"(20\d{2})\s*[年\-/.]\s*(\d{1,2})\s*[月\-/.]\s*(\d{1,2})\s*[日号]?")


def _date_year_from_text(text: str, value: str) -> str:
    """校正日期年份：优先采用材料原文中的年份，避免模型把年份改成当前年。

    规则：若提取值的「月日」在材料文本中出现，且该处的年份与提取值不同 → 用材料年份；
    若提取值的年份在材料中根本没有出现、但同月日在材料中出现 → 同样用材料年份。
    """
    m = _DATE_RE.search(str(value or ""))
    if not m or not text:
        return value
    year, month, day = m.group(1), int(m.group(2)), int(m.group(3))
    if f"{year}" in text and re.search(rf"{year}\s*[年\-/.]\s*{month}\s*[月\-/.]\s*{day}", text):
        return value                      # 年份在材料中确实出现，尊重提取值
    for mm in _DATE_RE.finditer(text):
        t_year, t_month, t_day = mm.group(1), int(mm.group(2)), int(mm.group(3))
        if t_month == month and t_day == day:
            return f"{t_year}年{t_month}月{t_day}日"
    return value


def extract_fields(text: str, filename: str = "") -> dict:
    """主入口：LLM 优先，规则兜底。"""
    if not text.strip():
        return {}
    result = _extract_by_llm(text)
    if result:
        return result
    return _extract_by_rules(text)


def _extract_by_llm(text: str) -> dict:
    if not llm.get_active_config():
        return {}
    fields_desc = "、".join(TARGET_FIELDS)
    data = llm.chat_json([
        {"role": "system", "content": "你是信息提取助手，只输出合法 JSON。"},
        {"role": "user", "content": EXTRACT_PROMPT.format(fields=fields_desc,
                                                          text=text[:6000])},
    ], max_tokens=config.AI_MAX_TOKENS)
    if not isinstance(data, dict):
        return {}
    # 清洗：只保留目标字段
    out = {k: (data.get(k) or "") for k in TARGET_FIELDS}
    for k in ("principal", "interest", "others", "claim_amount"):
        try:
            out[k] = float(out[k] or 0)
        except (TypeError, ValueError):
            out[k] = 0.0
    # 日期年份校正：以材料原文为准（防止把 2020 年写成当前年份）
    if str(out.get("claim_date") or "").strip():
        out["claim_date"] = _date_year_from_text(text, out["claim_date"])
    # 未提取到任何实质内容视为失败，交给规则兜底
    if not any(str(out.get(k, "")).strip() for k in
               ("name", "credit_code", "legal_rep", "claim_amount",
                "principal", "claim_category")):
        return {}
    return out


# ---------------- 规则兜底 ----------------

# 提取结果若命中标签词则视为无效（表格 OCR 文本常见）
_LABEL_WORDS = {
    "名称", "姓名", "电话", "手机", "联系电话", "联系人", "地址",
    "账号", "开户行", "开户人", "受托人", "身份证号", "邮编", "传真",
    "邮箱", "债权性质", "申报人", "债权人", "备注", "单位名称",
    "委托代理人", "法定代表人", "法人代表", "代理人", "负责人",
    "盖章", "签字", "盖章或签字", "申报人盖章", "申报人盖章或签字",
    "发包方", "甲方", "乙方", "无", "暂无", "未填写", "（未填写）",
    "组织机构信用代码", "统一社会信用代码", "信用代码", "开户许可证",
    "营业执照", "工程承包合同", "施工图片", "身份证", "证据名称", "备注",
}
_TAIL_CHARS = "：:（）()[]【】、，。；;"


def _clean_value(v: str) -> str:
    v = v.strip().strip(_TAIL_CHARS).strip()
    if not v or v in _LABEL_WORDS:
        return ""
    return v


def _kv_value(text: str, *keys: str) -> str:
    """匹配 '关键词：值' 形式。要求关键词前不是汉字（避免子串误匹配），
    关键词后必须有冒号/空白分隔；值无效时继续找下一个匹配。"""
    for key in keys:
        pat = r"(?<![\u4e00-\u9fa5])" + key + r"[\s:：]+([^\s，。；、,;（）()]{1,60})"
        for m in re.finditer(pat, text):
            v = _clean_value(m.group(1))
            if v:
                return v
    return ""


def _extract_name(text: str) -> str:
    """债权人名称：优先 '关键词：值'，其次表格 '名称' 标签后的行内容。"""
    v = _kv_value(text, "申报人", "债权人", "申报单位", "申请人",
                  "申报企业", "申报公司")
    if v:
        return v
    # 表格样式："名称\n巴中市经济开发区津梁花圃店"
    for m in re.finditer(r"(?<![\u4e00-\u9fa5])名称[\s:：]*\n?\s*([^\n，。；、,;]{2,60})",
                         text):
        v = _clean_value(m.group(1))
        if v and not re.fullmatch(r"[（(【\[].*", v):
            return v
    return ""


def _extract_by_rules(text: str) -> dict:
    out = {k: "" for k in TARGET_FIELDS}

    # 名称
    out["name"] = _extract_name(text)

    # 法定代表人
    out["legal_rep"] = _kv_value(text, "法定代表人", "法人代表")

    # 代理人
    out["agent_name"] = _kv_value(text, "委托代理人", "代理人")

    # 统一社会信用代码：18 位数字+字母（OCR 常混淆 O/0、I/1，放宽字符类）
    m = re.search(r"\b\d{17}[0-9A-Za-z]\b", text) or \
        re.search(r"\b[0-9A-Za-z]{18}\b", text)
    if m:
        out["credit_code"] = m.group(0).upper()

    # 身份证：18 位（17 数字 + 数字/X）
    m = re.search(r"\b\d{17}[\dXx]\b", text)
    if m:
        if not out["credit_code"]:
            out["credit_code"] = m.group(0)
        if not out["agent_id_no"]:
            out["agent_id_no"] = m.group(0)

    # 手机号（带词边界，避免匹配身份证号中间段）；优先取"电话/手机"关键词后
    phone = _kv_value(text, "电话", "手机", "联系电话", "联系方式")
    if phone and re.fullmatch(r"1[3-9]\d{9}", phone):
        out["contact_info"] = phone
    else:
        m = re.search(r"\b1[3-9]\d{9}\b", text)
        if m:
            out["contact_info"] = m.group(0)
    # 代理电话
    agent_phone = _kv_value(text, "代理人.*?电话", "委托人.*?电话")
    if not agent_phone:
        m2 = re.search(r"\b1[3-9]\d{9}\b", text[text.find("代理人") if "代理人" in text else 0:])
        if m2:
            agent_phone = m2.group(0)
    if agent_phone and agent_phone != out["contact_info"]:
        out["agent_contact"] = agent_phone

    # 固定电话 0xx-xxxxxxxx
    m = re.search(r"\b0\d{2,3}[-－—]?\d{7,8}\b", text)
    if m and not out["contact_info"]:
        out["contact_info"] = m.group(0)

    # 账号 / 开户行 / 地址（表格样式："账号\n200005336100016"）
    m = re.search(r"(?<![\u4e00-\u9fa5])账号[\s:：]*\n?\s*([0-9A-Za-z\- ]{6,30})", text)
    if m:
        out["account_no"] = m.group(1).strip()
    m = re.search(r"(?<![\u4e00-\u9fa5])开户行[\s:：]*\n?\s*([^\n，。；、]{4,50})", text)
    if m:
        v = _clean_value(m.group(1))
        if v:
            out["bank_name"] = v
    m = re.search(r"(?<![\u4e00-\u9fa5])联系地址[\s:：]*\n?\s*([^\n，。；、]{4,60})", text)
    if m:
        v = _clean_value(m.group(1))
        if v:
            out["address"] = v
    elif re.search(r"(?<![\u4e00-\u9fa5])通讯\s*信息", text):
        m2 = re.search(r"(?<![\u4e00-\u9fa5])联系地址[\s:：]*\n?\s*([^\n，。；、]{4,60})",
                       text)
        if m2:
            v = _clean_value(m2.group(1))
            if v:
                out["address"] = v

    # 金额：本金/利息/其他（优先关键词后金额）
    for key, out_key in [("本金", "principal"), ("利息", "interest"),
                         ("其他", "others")]:
        m = re.search(key + r"[\s:：]*人民币?\s*([\d,]+(?:\.\d{1,2})?)\s*(万)?元",
                      text)
        if m:
            amt = float(m.group(1).replace(",", ""))
            if m.group(2):
                amt *= 10000
            out[out_key] = amt

    # 总额：优先"合计/总额/共计 X元"
    m = re.search(r"(?:合计|总额|共计|总计)[\s:：]*人民币?\s*([\d,]+(?:\.\d{1,2})?)\s*(万)?元", text)
    if m:
        amt = float(m.group(1).replace(",", ""))
        if m.group(2):
            amt *= 10000
        out["claim_amount"] = amt
    else:
        m = re.search(r"(?:人民币|￥|¥)?\s*([\d,]+(?:\.\d{1,2})?)\s*(万)?元", text)
        if m:
            amt = float(m.group(1).replace(",", ""))
            if m.group(2):
                amt *= 10000
            out["claim_amount"] = amt
    # 本金未识别时用总额
    if not out["principal"] and out["claim_amount"]:
        out["principal"] = out["claim_amount"]

    # 日期：优先"申报时间"，其次任意日期（统一格式化为「2025年4月5日」）
    from .formatter import format_date_cn
    date_pat = r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*[日号]|" \
               r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}"
    m = re.search(r"申报时间[\s:：]*([0-9]{4}[^，。；\s]{0,20})", text)
    if m:
        out["claim_date"] = format_date_cn(m.group(1).strip())
    else:
        m = re.search(date_pat, text)
        if m:
            out["claim_date"] = format_date_cn(m.group(0).replace(" ", ""))

    # 诉讼状态
    if re.search(r"起诉|诉讼|判决|执行|立案", text):
        out["litigation_status"] = "是"

    # 债权性质关键词
    for kw, val in [("工程款", "工程款优先权"), ("抵押", "抵押债权"),
                    ("税收", "税收债权"), ("普通债权", "普通债权")]:
        if kw in text:
            out["claim_nature"] = val
            break

    # 债权种类关键词
    for kw, val in [("贷款", "金融"), ("借款", "借贷"), ("购销", "购销"),
                    ("货款", "购销"), ("买卖", "购销")]:
        if kw in text:
            out["claim_category"] = val
            break

    return out
