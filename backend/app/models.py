"""ORM 模型：项目、债权台账、申报材料文件、审查结果。"""
from datetime import datetime

from sqlalchemy import (
    Column, DateTime, ForeignKey, Integer, Numeric, String, Text, func,
)
from sqlalchemy.orm import relationship

from .database import Base


class Project(Base):
    """破产案件项目。"""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="项目名称")
    case_no = Column(String(100), default="", comment="案号")
    debtor = Column(String(200), default="", comment="债务人名称")
    manager = Column(String(100), default="", comment="管理人")
    accept_date = Column(String(30), default="", comment="破产受理日期（法院裁定受理日，利息止息基准）")
    cloud_code = Column(String(100), default="", comment="云端项目码（云端申报地址用，须与云端 CLOUD_PROJECT_CODES 一致）")
    remark = Column(Text, default="", comment="备注")
    status = Column(String(20), default="active", comment="active/closed")
    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="创建时间")


class Claim(Base):
    """债权人申报台账（字段与需求表一一对应）。"""

    __tablename__ = "claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    claim_no = Column(String(50), index=True, comment="债权编号 PC-001 自动生成（项目内唯一）")

    # ---- 债权人基本信息 ----
    name = Column(String(200), default="", comment="债权人名称（必填）")
    credit_code = Column(String(100), default="", comment="统一社会信用代码/身份证号码")
    legal_rep = Column(String(100), default="", comment="法定代表人/负责人")
    contact_info = Column(String(200), default="", comment="联系方式")
    address = Column(String(300), default="", comment="联系地址")

    # ---- 代理人 ----
    agent_name = Column(String(100), default="", comment="代理人姓名")
    agent_id_no = Column(String(100), default="", comment="代理人身份证号")
    agent_contact = Column(String(200), default="", comment="代理人联系方式")
    agent_address = Column(String(300), default="", comment="代理人地址")

    # ---- 收款账户 ----
    account_name = Column(String(100), default="", comment="开户名称")
    bank_name = Column(String(100), default="", comment="开户行")
    account_no = Column(String(100), default="", comment="账号")

    # ---- 债权要素 ----
    claim_category = Column(String(50), default="", comment="债权种类 金融/购销/借贷/其他")
    litigation_status = Column(String(20), default="", comment="涉诉涉执情况 是/否")
    claim_nature = Column(String(50), default="", comment="申报债权性质 工程款优先权/抵押债权/税收债权/普通债权")
    claim_date = Column(String(50), default="", comment="申报债权时间")
    principal = Column(Numeric(15, 2), default=0, comment="申报本金")
    interest = Column(Numeric(15, 2), default=0, comment="申报利息")
    others = Column(Numeric(15, 2), default=0, comment="申报其他")
    claim_amount = Column(Numeric(15, 2), default=0, comment="申报总额")

    # ---- 审核结果 ----
    audited_principal = Column(Numeric(15, 2), default=0, comment="审核本金")
    audited_interest = Column(Numeric(15, 2), default=0, comment="审核利息")
    audited_others = Column(Numeric(15, 2), default=0, comment="审核其他")
    audited_amount = Column(Numeric(15, 2), default=0, comment="审核总额")
    debt_nature = Column(String(50), default="", comment="债权性质")
    guarantee_notes = Column(Text, default="", comment="担保情况备注")
    claim_type = Column(String(50), default="", comment="债权类型")

    source_files = Column(Text, default="", comment="来源材料文件列表（JSON）")

    # ---- 流程状态 ----
    status = Column(String(20), default="pending",
                    comment="pending待登记/registered已登记/reviewed已复核")
    parse_status = Column(String(20), default="pending",
                          comment="解析状态 pending待解析/parsing解析中/done已完成/failed失败")
    parse_started_at = Column(DateTime, comment="本次解析开始时间（用于识别解析卡死/中断）")
    parse_error = Column(String(300), default="", comment="解析失败/超时原因")
    verified_at = Column(DateTime,
                         comment="初审/编辑或人工复核确认时间；有值表示台账数据为人工确认口径（AI 审查优先采用）")
    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), onupdate=datetime.now,
                        comment="更新时间")

    files = relationship("ClaimFile", backref="claim", order_by="ClaimFile.id",
                         cascade="all, delete-orphan")
    audit_results = relationship("AuditResult", backref="claim",
                                 cascade="all, delete-orphan")


class ClaimFile(Base):
    """申报材料文件。"""

    __tablename__ = "claim_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    filename = Column(String(255), nullable=False, comment="原始文件名")
    stored_name = Column(String(255), default="", comment="存储文件名")
    file_type = Column(String(20), default="", comment="pdf/word/image/other")
    file_path = Column(String(500), default="", comment="相对存储路径")
    size = Column(Integer, default=0, comment="字节数")
    ocr_text = Column(Text, default="", comment="解析出的文本内容")
    parse_status = Column(String(20), default="pending",
                          comment="pending待解析/done已解析/failed失败/empty无文本")
    parse_engine = Column(String(20), default="",
                          comment="解析引擎 mineru云端/local本地/空")
    origin = Column(String(20), default="",
                    comment="材料来源：空=首次申报材料 / supplement=补充材料")
    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="创建时间")


class OnlineClaim(Base):
    """在线申报（公开网页提交，待管理人导入台账）。"""

    __tablename__ = "online_claims"

    id = Column(Integer, primary_key=True, autoincrement=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=False, index=True)
    submit_no = Column(String(50), index=True, comment="申报流水号 WS-0001（项目内唯一）")

    # ---- 债权人信息（与台账字段对齐） ----
    name = Column(String(200), default="", comment="债权人名称（必填）")
    credit_code = Column(String(100), default="", comment="统一社会信用代码/身份证号码")
    legal_rep = Column(String(100), default="", comment="法定代表人/负责人")
    contact_info = Column(String(200), default="", comment="联系方式")
    address = Column(String(300), default="", comment="联系地址")

    # ---- 债权要素 ----
    claim_category = Column(String(50), default="", comment="债权种类 金融/购销/借贷/其他")
    claim_nature = Column(String(50), default="", comment="申报债权性质 工程款优先权/抵押债权/税收债权/普通债权")
    claim_date = Column(String(50), default="", comment="申报债权时间")
    principal = Column(Numeric(15, 2), default=0, comment="申报本金")
    interest = Column(Numeric(15, 2), default=0, comment="申报利息")
    others = Column(Numeric(15, 2), default=0, comment="申报其他")
    claim_amount = Column(Numeric(15, 2), default=0, comment="申报总额")
    remark = Column(Text, default="", comment="债权人补充说明")

    # ---- 流程状态 ----
    status = Column(String(20), default="new",
                    comment="new待导入/imported已导入/ignored已忽略")
    imported_claim_id = Column(Integer, default=0, comment="导入后对应的台账债权 ID")
    ip_addr = Column(String(50), default="", comment="提交 IP")
    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="提交时间")

    # ---- 云端同步（阿里云接收服务拉取） ----
    cloud_claim_id = Column(String(100), default="", index=True,
                            comment="云端申报号（C-xxx），防重复拉取")
    cloud_pulled_at = Column(DateTime, nullable=True, comment="从云端拉取时间")

    files = relationship("OnlineClaimFile", backref="online_claim",
                         order_by="OnlineClaimFile.id",
                         cascade="all, delete-orphan")


class OnlineClaimFile(Base):
    """在线申报上传的材料文件（导入台账时复制进债权目录）。"""

    __tablename__ = "online_claim_files"

    id = Column(Integer, primary_key=True, autoincrement=True)
    online_claim_id = Column(Integer, ForeignKey("online_claims.id"),
                             nullable=False, index=True)
    filename = Column(String(255), nullable=False, comment="原始文件名")
    stored_name = Column(String(255), default="", comment="存储文件名")
    file_type = Column(String(20), default="", comment="pdf/word/image/other")
    file_path = Column(String(500), default="", comment="相对存储路径")
    size = Column(Integer, default=0, comment="字节数")
    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="创建时间")


class CloudConfig(Base):
    """云端申报同步配置（单行，id=1）。"""

    __tablename__ = "cloud_config"

    id = Column(Integer, primary_key=True)
    cloud_url = Column(String(300), default="", comment="云端接收服务地址")
    admin_token = Column(String(200), default="", comment="云端管理员令牌")
    project_id = Column(Integer, default=0, comment="默认拉取目标项目 ID")
    last_sync_at = Column(DateTime, nullable=True, comment="最近一次拉取时间")
    updated_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), onupdate=datetime.now,
                        comment="更新时间")


class AIConfig(Base):
    """AI 模型配置（可在系统内添加/切换多个 OpenAI 兼容模型）。"""

    __tablename__ = "ai_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False, comment="配置名称，如 DeepSeek / 通义千问")
    base_url = Column(String(300), default="", comment="接口地址（OpenAI 兼容）")
    api_key = Column(String(300), default="", comment="API Key")
    model = Column(String(100), default="", comment="模型名，如 deepseek-chat")
    is_active = Column(Integer, default=0, comment="是否当前激活 1/0")
    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), onupdate=datetime.now,
                        comment="更新时间")


class AuditResult(Base):
    """债权审查结果（AI 审查 + 人工复核）。"""

    __tablename__ = "audit_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    claim_id = Column(Integer, ForeignKey("claims.id"), nullable=False, index=True)

    ai_status = Column(String(20), default="none",
                       comment="none未审查/running审查中/done完成/failed失败")
    ai_opinion = Column(Text, default="", comment="AI 审查意见（JSON 文本）")
    ai_model = Column(String(100), default="", comment="AI 模型名")
    ai_error = Column(Text, default="", comment="AI 错误信息")
    prompt_version = Column(String(30), default="",
                            comment="审查提示词版本（便于追溯历史结论）")
    injected_standards = Column(String(200), default="",
                                comment="本次注入的类型化审查标准（工程款/借贷/…）")
    injected_case_info = Column(String(500), default="",
                                comment="本次注入的案件信息（含破产受理日，期间判断基准）")

    manual_status = Column(String(20), default="none",
                           comment="none未复核/done已复核")
    manual_opinion = Column(Text, default="", comment="人工审查意见")
    audit_conclusion = Column(String(50), default="", comment="审查结论 认可/部分认可/不认可")
    auditor = Column(String(100), default="", comment="审查人")
    audited_at = Column(DateTime, comment="人工复核时间")

    # 意见书编辑稿（JSON：人工预览/编辑后的最终内容，导出优先使用；空则用 AI 意见生成）
    opinion_draft = Column(Text, default="", comment="意见书编辑稿（JSON）")

    # AI 审查启动时间（本地时间；用于判断 running 是否已中断）
    ai_started_at = Column(DateTime, nullable=True, comment="AI 审查启动时间")

    created_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now,
                        server_default=func.now(), onupdate=datetime.now,
                        comment="更新时间")
