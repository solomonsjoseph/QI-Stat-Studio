from pydantic import BaseModel, ConfigDict
from typing import Any, Optional, List, Dict


class ProjectCreate(BaseModel):
    title: str
    description: str
    deadline: Optional[str] = None


class ProjectOut(BaseModel):
    id: int
    title: str
    description: str
    status: str
    deadline: Optional[str]

    model_config = ConfigDict(from_attributes=True)


class IntakeAnswerIn(BaseModel):
    question_key: str
    answer: str
    is_unsure: bool = False


class AnalysisRequest(BaseModel):
    project_id: int
    upload_id: int
    template: str
    parameters: Dict[str, Any]


class AIRequest(BaseModel):
    project_id: int
    messages: List[Dict[str, str]]


class ColumnTypeUpdate(BaseModel):
    column_map: Dict[str, str]


class MentorComment(BaseModel):
    text: str


class EditIn(BaseModel):
    field: str
    edited_text: str


class AppSettingIn(BaseModel):
    key: str
    value: str
