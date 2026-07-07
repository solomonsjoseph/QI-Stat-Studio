from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ProjectCreate(BaseModel):
    title: str
    description: str = ""
    deadline: Optional[str] = None


class ProjectUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    status: Optional[str] = None
    deadline: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    title: str
    description: Optional[str] = ""
    status: str
    deadline: Optional[str] = None
    owner_user_id: Optional[int] = None
    archived_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UploadOut(BaseModel):
    id: int
    project_id: int
    filename: str
    original_filename: str
    file_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime
    col_types: dict[str, str]
    column_map: dict[str, str]
    quality_flags: list[dict[str, Any]]
    acknowledged_flags: Optional[list[dict[str, Any]]]
    status: str


class AnalysisRunOut(BaseModel):
    id: int
    project_id: int
    upload_id: Optional[int]
    template: str
    parameters: dict[str, Any]
    result: dict[str, Any]
    created_at: datetime


class ShareOut(BaseModel):
    token: str
    project_id: int
    mentor_email: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class ShareCreateIn(BaseModel):
    mentor_email: Optional[str] = None
    expires_at: Optional[datetime] = None


class ShareMutationIn(BaseModel):
    token: Optional[str] = None
    mentor_email: Optional[str] = None


class ProjectListResponse(BaseModel):
    items: list[ProjectOut]
    total: int
    limit: int
    offset: int


class ProjectResumeOut(BaseModel):
    project: ProjectOut
    answers: dict[str, Any]
    latest_upload: Optional[UploadOut]
    latest_run: Optional[AnalysisRunOut]
    latest_share: Optional[ShareOut]
    current_screen: str


class IntakeAnswerIn(BaseModel):
    question_key: str
    answer: str
    is_unsure: bool = False


class AnswerPayload(BaseModel):
    answers: dict[str, Any]


class AnalysisRequest(BaseModel):
    project_id: int
    upload_id: int
    template: str
    parameters: dict[str, Any]

    model_config = ConfigDict(extra="forbid")


class AIRequest(BaseModel):
    project_id: int
    messages: list[dict[str, str]]


class ChatRequest(BaseModel):
    project_id: int
    messages: list[dict[str, str]]
    model: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    phi_redacted: bool
    redaction_count: int


class IntakePrefillRequest(BaseModel):
    project_id: int
    description: str


class IntakePrefillResponse(BaseModel):
    answers: dict[str, Any]
    phi_redacted: bool
    redaction_count: int


class ColumnTypeUpdate(BaseModel):
    col_types: dict[str, str]
    column_map: dict[str, str] = Field(default_factory=dict)


class EditIn(BaseModel):
    field: Literal["title", "caption", "interpretation"]
    original_text: str = ""
    edited_text: str


class MentorCommentIn(BaseModel):
    author_name: str
    author_email: Optional[str] = None
    text: str


class MentorCommentOut(BaseModel):
    id: int
    author_name: str
    author_email: Optional[str]
    text: str
    created_at: datetime
    updated_at: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class CommentPayload(MentorCommentIn):
    pass


class MentorCommentEditIn(BaseModel):
    author_email: Optional[str] = None
    text: str


class MentorCommentAuthorIn(BaseModel):
    author_email: Optional[str] = None


class SettingOut(BaseModel):
    key: str
    value: str
    type: str
    secret: bool
    runtime: bool


class SettingUpdate(BaseModel):
    key: str
    value: str


class SettingPayload(SettingUpdate):
    pass


class AppSettingIn(SettingUpdate):
    pass


class UserOut(BaseModel):
    id: int
    email: str
    role: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuthCredentials(BaseModel):
    email: str
    password: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    field_errors: dict[str, list[str]] = Field(default_factory=dict)
    request_id: str


class ErrorEnvelope(BaseModel):
    error: ErrorDetail
