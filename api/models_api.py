from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

FieldStatus = Literal["inferred", "user-confirmed", "user-corrected", "unknown"]

class InterventionDesign(BaseModel):
    present: bool = False
    description: str | None = None
    start_date: str | None = None          # YYYY-MM-DD

class TimeStructureDesign(BaseModel):
    has_dates: bool = False
    date_column: str | None = None
    granularity: Literal["day", "week", "month", "quarter"] | None = None

class OutcomeDesign(BaseModel):
    label: str
    column: str | None = None
    kind: Literal["proportion", "rate", "count", "continuous", "binary", "unknown"] = "unknown"
    denominator_column: str | None = None

class ProjectDesign(BaseModel):
    aim: str = ""
    population: str = ""
    setting: str | None = None
    intervention: InterventionDesign = InterventionDesign()
    primary_outcome: OutcomeDesign | None = None
    secondary_outcomes: list[OutcomeDesign] = []
    comparison: Literal["pre-post", "time-series", "single-group", "between-group", "none"] = "none"
    time_structure: TimeStructureDesign = TimeStructureDesign()
    unit_of_analysis: Literal["patient", "encounter", "period", "other", "unknown"] = "unknown"
    group_column: str | None = None
    pre_label: str | None = None
    post_label: str | None = None
    paired: bool | None = None             # None = not yet established
    pairing_id_column: str | None = None
    design_type: str | None = None
    confidence: dict[str, Literal["high", "medium", "low"]] = {}
    status: dict[str, FieldStatus] = {}    # keyed by dotted field path
    plain_restatement: str = ""
    sufficient_to_continue: bool = False

    model_config = ConfigDict(extra="ignore")

    @field_validator("primary_outcome", mode="before")
    @classmethod
    def _coerce_outcome(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"label": value}
        return value

    @field_validator("intervention", mode="before")
    @classmethod
    def _coerce_intervention(cls, value: Any) -> Any:
        if isinstance(value, str):
            clean = value.strip().lower()
            if clean in ("none", "no", "false", "no intervention", "null", ""):
                return {"present": False, "description": None, "start_date": None}
            return {"present": True, "description": value}
        return value

    @field_validator("time_structure", mode="before")
    @classmethod
    def _coerce_time_structure(cls, value: Any) -> Any:
        if isinstance(value, str):
            gran = value.lower() if value.lower() in ("day", "week", "month", "quarter") else None
            return {"has_dates": True, "granularity": gran}
        return value

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
    ai_clarification_state: Optional[dict[str, Any]] = None
    ai_project_design: Optional[dict[str, Any]] = None
    ai_analysis_plan: Optional[dict[str, Any]] = None
    ai_plan_history: Optional[dict[str, Any]] = None
    data_collection_notes: Optional[dict[str, Any]] = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator(
        "ai_clarification_state", "ai_project_design", "ai_analysis_plan", "ai_plan_history", "data_collection_notes",
        mode="before",
    )
    @classmethod
    def _parse_ai_state_json(cls, value: Any) -> Optional[dict[str, Any]]:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return None
        return value


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
    column_roles: dict[str, str] = Field(default_factory=dict)
    quality_flags: list[dict[str, Any]]
    acknowledged_flags: Optional[list[dict[str, Any]]]
    status: str
    preview_rows: list[dict[str, Any]] = Field(default_factory=list)
    dataset_profile: Optional[dict[str, Any]] = None

    @field_validator("dataset_profile", mode="before")
    @classmethod
    def _parse_dataset_profile(cls, value: Any) -> Optional[dict[str, Any]]:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return None
        return value

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
    latest_upload: Optional[UploadOut]
    latest_run: Optional[AnalysisRunOut]
    runs: list[dict[str, Any]] = []
    latest_share: Optional[ShareOut]
    current_screen: str

class AnalysisRequest(BaseModel):
    project_id: int
    upload_id: int
    template: str
    parameters: dict[str, Any]

    model_config = ConfigDict(extra="forbid")



class ChatRequest(BaseModel):
    project_id: int
    messages: list[dict[str, str]]
    model: Optional[str] = None


class ChatResponse(BaseModel):
    content: str
    phi_redacted: bool
    redaction_count: int



class ScrubPreviewRequest(BaseModel):
    text: str


class ScrubPreviewResponse(BaseModel):
    text: str
    redacted: bool
    count: int


class ClarifyRequest(BaseModel):
    message: Optional[str] = None
    confirm: Optional[bool] = None


class ClarifyTurn(BaseModel):
    role: Literal["ai", "user"]
    content: str
    reasoning: Optional[str] = None


class ClarifyResponse(BaseModel):
    message: str
    reasoning: Optional[str] = None
    suggested_title: Optional[str] = None
    suggested_description: Optional[str] = None
    confirmed: bool
    turns: list[ClarifyTurn]
    design: Optional[dict[str, Any]] = None


class AnalysisPlanRequest(BaseModel):
    message: Optional[str] = None
    confirm: Optional[bool] = None
    analyses: Optional[list[dict[str, Any]]] = None



class AnalysisPlanItem(BaseModel):
    id: str = ""
    template: str
    display_name: str = ""
    question: str = ""
    rationale: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    param_confidence: dict[str, Literal["high", "medium", "low"]] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    executable: bool = False
    errors: list[str] = Field(default_factory=list)
    missing_params: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")

class AnalysisPlanTurn(BaseModel):
    role: Literal["ai", "user"]
    content: str
    reasoning: Optional[str] = None


class AnalysisPlanResponse(BaseModel):
    message: str
    reasoning: Optional[str] = None
    confirmed: bool
    analyses: list[AnalysisPlanItem]
    turns: list[AnalysisPlanTurn]

class RecommendPlanModel(BaseModel):
    message: str = ""
    reasoning: Optional[str] = None
    confirmed: bool = False
    analyses: list[AnalysisPlanItem] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class RunInterpretation(BaseModel):
    run_id: int
    text: str


class InterpretResultsResponse(BaseModel):
    interpretations: list[RunInterpretation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    abstract_draft: str = ""

    model_config = ConfigDict(extra="ignore")


class OverridePlanRequest(BaseModel):
    instruction: str


class OverridePlanResponse(BaseModel):
    message: str
    changes: list[str] = Field(default_factory=list)
    confirmed: bool = False
    analyses: list[AnalysisPlanItem] = Field(default_factory=list)


class ValidatePlanRequest(BaseModel):
    upload_id: int
    analyses: list[dict[str, Any]]


class ValidatePlanResponse(BaseModel):
    items: list[dict[str, Any]]
    feasible_templates: list[str]


class RunPlanRequest(BaseModel):
    upload_id: int
    analyses: list[dict[str, Any]]

class ColumnTypeUpdate(BaseModel):
    col_types: dict[str, str]
    column_map: dict[str, str] = Field(default_factory=dict)
    column_roles: dict[str, str] = Field(default_factory=dict)


class EditIn(BaseModel):
    field: Literal["title", "caption", "interpretation"]
    run_id: Optional[int] = None
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
