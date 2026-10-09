"""Pydantic 请求/响应模型。"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class ProjectCreate(BaseModel):
    name: str
    case_no: str = ""
    debtor: str = ""
    manager: str = ""
    accept_date: str = ""
    cloud_code: str = ""
    remark: str = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    case_no: Optional[str] = None
    debtor: Optional[str] = None
    manager: Optional[str] = None
    accept_date: Optional[str] = None
    cloud_code: Optional[str] = None
    remark: Optional[str] = None
    status: Optional[str] = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    case_no: str = ""
    debtor: str = ""
    manager: str = ""
    accept_date: str = ""
    cloud_code: str = ""
    remark: str = ""
    status: str = "active"
    created_at: datetime


class ClaimUpdate(BaseModel):
    """台账可编辑字段（人工登记/复核）。"""

    name: Optional[str] = None
    credit_code: Optional[str] = None
    legal_rep: Optional[str] = None
    contact_info: Optional[str] = None
    address: Optional[str] = None
    agent_name: Optional[str] = None
    agent_id_no: Optional[str] = None
    agent_contact: Optional[str] = None
    agent_address: Optional[str] = None
    account_name: Optional[str] = None
    bank_name: Optional[str] = None
    account_no: Optional[str] = None
    claim_category: Optional[str] = None
    litigation_status: Optional[str] = None
    claim_nature: Optional[str] = None
    claim_date: Optional[str] = None
    principal: Optional[float] = None
    interest: Optional[float] = None
    others: Optional[float] = None
    claim_amount: Optional[float] = None
    audited_principal: Optional[float] = None
    audited_interest: Optional[float] = None
    audited_others: Optional[float] = None
    audited_amount: Optional[float] = None
    debt_nature: Optional[str] = None
    guarantee_notes: Optional[str] = None
    claim_type: Optional[str] = None


class ClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    claim_no: str
    name: str
    credit_code: str = ""
    legal_rep: str = ""
    contact_info: str = ""
    address: str = ""
    agent_name: str = ""
    agent_id_no: str = ""
    agent_contact: str = ""
    agent_address: str = ""
    account_name: str = ""
    bank_name: str = ""
    account_no: str = ""
    claim_category: str = ""
    litigation_status: str = ""
    claim_nature: str = ""
    claim_date: str = ""
    principal: float = 0
    interest: float = 0
    others: float = 0
    claim_amount: float = 0
    audited_principal: float = 0
    audited_interest: float = 0
    audited_others: float = 0
    audited_amount: float = 0
    debt_nature: str = ""
    guarantee_notes: str = ""
    claim_type: str = ""
    source_files: str = ""
    status: str = "pending"
    parse_status: str = "pending"
    parse_error: str = ""
    verified_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class FileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    claim_id: int
    project_id: int
    filename: str
    file_type: str
    size: int
    ocr_text: str = ""
    parse_status: str = "pending"
    parse_engine: str = ""
    origin: str = ""
    created_at: datetime


class AuditResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    claim_id: int
    ai_status: str = "none"
    ai_opinion: str = ""
    ai_model: str = ""
    ai_error: str = ""
    prompt_version: str = ""
    injected_standards: str = ""
    injected_case_info: str = ""
    manual_status: str = "none"
    manual_opinion: str = ""
    audit_conclusion: str = ""
    auditor: str = ""
    audited_at: Optional[datetime] = None
    opinion_draft: str = ""
    created_at: datetime


class OnlineClaimFileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    filename: str
    file_type: str
    size: int
    created_at: datetime


class OnlineClaimOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    submit_no: str
    name: str
    credit_code: str = ""
    legal_rep: str = ""
    contact_info: str = ""
    address: str = ""
    claim_category: str = ""
    claim_nature: str = ""
    claim_date: str = ""
    principal: float = 0
    interest: float = 0
    others: float = 0
    claim_amount: float = 0
    remark: str = ""
    status: str = "new"
    imported_claim_id: int = 0
    cloud_claim_id: str = ""
    created_at: datetime
    files: list[OnlineClaimFileOut] = []


class AIConfigIn(BaseModel):
    name: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    activate: bool = False


class AIConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    is_active: bool = False
    created_at: datetime
    updated_at: Optional[datetime] = None


class ManualAuditIn(BaseModel):
    manual_opinion: str = ""
    audit_conclusion: str = ""          # 认可/部分认可/不认可
    auditor: str = ""
    debt_nature: str = ""               # 确认债权性质（7 类标准）
    audited_principal: Optional[float] = None
    audited_interest: Optional[float] = None
    audited_others: Optional[float] = None
    audited_amount: Optional[float] = None
