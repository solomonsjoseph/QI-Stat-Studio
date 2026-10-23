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
    gating: Optional[GatingOut] = None

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
    flag_reviewed: bool = False             # resident pressed "I've reviewed this" on the needs-clarification flag
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


class PlanExplainItem(BaseModel):
    """Prose-only overlay for a rule-built plan item. Templates/params are ignored if present."""

    id: str = ""
    template: str = ""
    display_name: str = ""
    question: str = ""
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class RecommendExplainModel(BaseModel):
    """LLM explain-only response. Never used to select templates or confirm the plan."""

    message: str = ""
    reasoning: Optional[str] = None
    analyses: list[PlanExplainItem] = Field(default_factory=list)

    model_config = ConfigDict(extra="ignore")


class RunInterpretation(BaseModel):
    run_id: int
    text: str


class InterpretResultsResponse(BaseModel):
    interpretations: list[RunInterpretation] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    abstract_draft: str = ""
    needs_review_flags: list[str] = Field(default_factory=list)

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


# ---------------------------------------------------------------------------
# Handoff / warning-group / advisor contract (task T5). Contract only: no
# endpoint or DB uses these yet. See docs/api-contract-handoff.md.
# ---------------------------------------------------------------------------

GroupAction = Literal["acknowledge", "clarify"]
GroupStatus = Literal["open", "discussing", "handled"]
# unhandled: in no group. open/discussing: in a group of that status.
# handled: group handled (warnings). resolved: ERROR no longer present on cleaned data.
FlagState = Literal["unhandled", "open", "discussing", "handled", "resolved"]
StepOp = Literal["recode", "merge_values", "trim", "change_case", "retype", "rename_column", "set_value",
                 "drop_duplicates", "drop_rows", "drop_column", "set_role", "note"]   # mirrors api/cleaning_steps.OPS
KeySource = Literal["settings", "env", "none"]


class WarningGroupCreate(BaseModel):
    flag_ids: list[str] = Field(min_length=1)
    action: GroupAction
    text: str | None = None                 # optional at creation (note for acknowledge, first message for clarify)


class WarningBatchAcknowledge(BaseModel):
    flag_ids: list[str] = Field(min_length=1)   # WARNING flags only; ERROR ids -> 422
    text: str | None = None


class WarningGroupOut(BaseModel):
    id: int
    project_id: int
    upload_id: int
    flag_ids: list[str]
    action: GroupAction
    text: str | None = None
    status: GroupStatus
    turn_count: int = 0
    created_at: datetime
    updated_at: datetime
    handled_at: datetime | None = None


class WarningGroupListOut(BaseModel):
    upload_id: int
    groups: list[WarningGroupOut]


class FlagStateOut(BaseModel):
    flag_id: str
    severity: Literal["WARNING", "ERROR"]
    state: FlagState
    group_id: int | None = None
    action: GroupAction | None = None


class FlagStatesOut(BaseModel):
    upload_id: int
    flags: list[FlagStateOut]
    unhandled_warning_count: int
    unresolved_error_count: int
    pending_choice: bool = False


class CleaningStep(BaseModel):
    """Step shape shared with api/cleaning_steps.py (T4). Extra keys are the op's args."""
    model_config = ConfigDict(extra="allow")
    op: StepOp
    warning_ids: list[str] = Field(default_factory=list)
    note: str = ""


class HandoffRevisionOut(BaseModel):
    revision: int
    created_at: datetime
    actor: Literal["user", "advisor", "system"] = "advisor"
    kind: Literal["created", "apply", "undo", "revise", "keep_from_previous"] = "apply"
    group_id: int | None = None
    summary: str = ""
    rows_affected: dict[str, int] = Field(default_factory=dict)   # step index (as str) -> rows


class HandoffOut(BaseModel):
    upload_id: int
    project_id: int
    status: Literal["none", "pending_choice", "current", "replaced", "deleted"]
    revision: int
    markdown: str | None = None             # None when the document was deleted
    steps: list[CleaningStep] = Field(default_factory=list)
    change_log: list[HandoffRevisionOut] = Field(default_factory=list)
    updated_at: datetime | None = None
    read_only: bool = False


class HandoffRevisionListOut(BaseModel):
    upload_id: int
    revisions: list[HandoffRevisionOut]


class HandoffHistoryItem(BaseModel):
    upload_id: int
    file_name: str
    created_at: datetime
    replaced_at: datetime | None = None
    status: Literal["current", "replaced", "deleted"]   # "deleted" = document removed, log kept
    revision: int
    change_log_entries: int


class HandoffHistoryOut(BaseModel):
    project_id: int
    items: list[HandoffHistoryItem]


class AdvisorMessageIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)   # PHI-scrubbed server-side
    warning_id: str | None = None           # which warning the reply is about; None = whole group


class ProposedSteps(BaseModel):
    warning_id: str
    steps: list[CleaningStep] = Field(default_factory=list)   # empty = note only, no data change
    summary: str = ""
    dry_run: list[dict[str, Any]] = Field(default_factory=list)   # per-step rows_changed etc. from apply_steps


class AdvisorTurnOut(BaseModel):
    role: Literal["user", "advisor"]
    text: str
    warning_id: str | None = None
    created_at: datetime


class AdvisorReply(BaseModel):
    advisor_available: bool = True
    group_id: int
    group_status: GroupStatus
    message: str                            # advisor text
    proposals: list[ProposedSteps] = Field(default_factory=list)
    needs_user_confirmation: bool = False
    proposal_id: str | None = None          # echoed back in confirm; changes on every new proposal
    mode: Literal["propose", "undo", "revise", "info"] = "propose"
    unapplied_notes: list[str] = Field(default_factory=list)  # requests outside the step vocabulary
    dry_run_error: str | None = None        # set when the proposal failed its dry run on the data


class AdvisorConfirmIn(BaseModel):
    proposal_id: str
    decline: bool = False                   # True drops the proposal without applying


class AdvisorConfirmOut(BaseModel):
    group_id: int
    group_status: GroupStatus
    applied: bool
    handoff_revision: int
    rows_affected: dict[str, int] = Field(default_factory=dict)
    flag_states: FlagStatesOut              # recomputed on the cleaned data
    column_roles: dict[str, str] | None = None   # Upload.column_roles after the confirm, so the role table can refresh


class AdvisorThreadOut(BaseModel):
    group: WarningGroupOut
    turns: list[AdvisorTurnOut]
    pending: AdvisorReply | None = None     # last unconfirmed proposal, if any
    advisor_available: bool


class AdvisorUnavailableError(BaseModel):
    """Body of the HTTP 503 returned by advisor/AI endpoints when no AI can answer."""
    error: ErrorDetail                      # code = "advisor_unavailable"
    advisor_available: Literal[False] = False
    reason: Literal["no_key", "provider_error", "rate_limited"]
    key_source: KeySource
    manual_path_available: bool = True


class ReuploadFollowUpIn(BaseModel):
    choice: Literal["keep", "fresh"]


class ReuploadFollowUpOut(BaseModel):
    upload_id: int
    choice: Literal["keep", "fresh"]
    handoff: HandoffOut


class ReplaceUploadExtra(BaseModel):
    """Fields added to the replace response, alongside every existing UploadOut field."""
    same_as_previous: bool = False          # file and dictionary checksums both match the replaced upload
    started_fresh: bool = False             # different file: new handoff already built, old one moved to history
    choice_required: bool = False           # same_as_previous and no choice made yet


class AIKeyIn(BaseModel):
    value: str = Field(min_length=8, max_length=512)   # write-only


class AIKeyPayload(BaseModel):
    """Body of PUT /settings/ai-key (the live request shape; AIKeyIn above is not wired to a route)."""
    key: str = Field(min_length=8, max_length=512)


class AIKeyStatus(BaseModel):
    configured: bool
    source: KeySource
    last4: str | None
    provider: str
    advisor_available: bool


class ProviderStatusOut(BaseModel):
    advisor_available: bool
    key_source: KeySource
    provider: str | None = None             # e.g. "stub", "gemini", "openrouter"


class GatingOut(BaseModel):
    """Added to the resume / current-screen payload (ProjectResumeOut.gating)."""
    unhandled_warning_count: int = 0
    unresolved_error_count: int = 0
    open_group_count: int = 0
    can_continue: bool = True               # unhandled == 0 and unresolved errors == 0
    handoff_status: Literal["none", "pending_choice", "current", "replaced", "deleted"] = "none"
    advisor_available: bool = False
    pending_choice: bool = False            # identical-file re-upload awaiting keep/fresh; forces can_continue false


class AdvisorModelProposal(BaseModel):
    warning_id: str
    summary: str = ""
    steps: list[dict[str, Any]] = Field(default_factory=list)


class AdvisorModelOut(BaseModel):
    """What the LLM must return (see ADVISOR_SYSTEM_V1)."""
    message: str
    mode: Literal["propose", "undo", "revise", "info"] = "propose"
    proposals: list[AdvisorModelProposal] = Field(default_factory=list)
    unapplied_notes: list[str] = Field(default_factory=list)
