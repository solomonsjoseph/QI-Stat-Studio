from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from api.database import Base


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    description = Column(Text)
    status = Column(String(50), default="draft")
    deadline = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Upload(Base):
    __tablename__ = "uploads"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    filename = Column(String(255))
    column_map = Column(Text, default="{}")
    col_types = Column(Text, default="{}")
    quality_flags = Column(Text, default="[]")
    encrypted_path = Column(String(512))


class IntakeAnswer(Base):
    __tablename__ = "intake_answers"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    question_key = Column(String(10))
    answer = Column(Text)
    is_unsure = Column(Boolean, default=False)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    template = Column(String(50))
    parameters = Column(Text, default="{}")
    result_json = Column(Text, default="{}")
    code_r = Column(Text, default="")
    code_spss = Column(Text, default="")
    code_sas = Column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    action = Column(String(100))
    metadata_json = Column(Text, default="{}")
    timestamp = Column(DateTime, default=datetime.utcnow)


class EditHistory(Base):
    __tablename__ = "edit_history"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    field = Column(String(100))
    original_text = Column(Text)
    edited_text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class MentorShare(Base):
    __tablename__ = "mentor_shares"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"))
    token = Column(String(128), unique=True)
    mentor_email = Column(String(255), nullable=True)
    comments_json = Column(Text, default="[]")


class FailureLog(Base):
    __tablename__ = "failure_log"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id"), nullable=True)
    error_type = Column(String(100))
    template = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text)
