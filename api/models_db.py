from datetime import datetime
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, ForeignKey
from api.database import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(Text, nullable=False)
    role = Column(String(50), default="resident", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    disabled_at = Column(DateTime, nullable=True)


class UserSession(Base):
    __tablename__ = "user_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash = Column(String(128), unique=True, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    revoked_at = Column(DateTime, nullable=True)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    description = Column(Text)
    status = Column(String(50), default="draft")
    deadline = Column(String(20), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    archived_at = Column(DateTime, nullable=True)
    schema_version = Column(Integer, server_default="1", default=1, nullable=False)
    workflow_phase = Column(String(32), server_default="intake", default="intake", nullable=False)
    ai_clarification_state = Column(Text, nullable=True)
    ai_project_design = Column(Text, nullable=True)
    ai_analysis_plan = Column(Text, nullable=True)
    ai_plan_history = Column(Text, nullable=True)
    inputs_fingerprint = Column(String(64), nullable=True)
    data_collection_notes = Column(Text, nullable=True)

class Upload(Base):
    __tablename__ = "uploads"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    filename = Column(String(255))
    column_map = Column(Text, default="{}")
    col_types = Column(Text, default="{}")
    quality_flags = Column(Text, default="[]")
    acknowledged_flags = Column(Text, nullable=True)
    encrypted_path = Column(String(512))
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    file_type = Column(String(20), default="unknown", nullable=False)
    size_bytes = Column(Integer, default=0, nullable=False)
    checksum_sha256 = Column(String(64), default="", nullable=False)
    original_filename = Column(String(255), default="", nullable=False)
    storage_key = Column(String(512), default="", nullable=False)
    status = Column(String(20), default="active", nullable=False)
    phi_scan_status = Column(String(20), default="pending", nullable=False)
    dataset_profile = Column(Text, nullable=True)
    phi_scan_detail = Column(Text, nullable=True)
    column_roles = Column(Text, server_default="{}", default="{}", nullable=False)
    dictionary_filename = Column(String(255), nullable=True)
    dictionary_text = Column(Text, nullable=True)


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    upload_id = Column(Integer, ForeignKey("uploads.id", ondelete="CASCADE"), nullable=True)
    template = Column(String(50))
    parameters = Column(Text, default="{}")
    result_json = Column(Text, default="{}")
    code_r = Column(Text, default="")
    code_spss = Column(Text, default="")
    code_sas = Column(Text, default="")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_log"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    action = Column(String(100))
    metadata_json = Column(Text, default="{}")
    timestamp = Column(DateTime, default=datetime.utcnow)


class EditHistory(Base):
    __tablename__ = "edit_history"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    run_id = Column(Integer, ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=True)
    field = Column(String(100))
    original_text = Column(Text)
    edited_text = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class MentorShare(Base):
    __tablename__ = "mentor_shares"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"))
    token = Column(String(128), unique=True)
    mentor_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)
    regenerated_from_id = Column(Integer, ForeignKey("mentor_shares.id", ondelete="SET NULL"), nullable=True)


class MentorComment(Base):
    __tablename__ = "mentor_comments"
    id = Column(Integer, primary_key=True)
    share_id = Column(Integer, ForeignKey("mentor_shares.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    author_name = Column(String(255), nullable=False)
    author_email = Column(String(255), nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)


class AIUsageEvent(Base):
    __tablename__ = "ai_usage_events"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    model = Column(String(255), nullable=False)
    prompt_chars = Column(Integer, default=0, nullable=False)
    completion_chars = Column(Integer, default=0, nullable=False)
    status = Column(String(50), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class FailureLog(Base):
    __tablename__ = "failure_log"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    error_type = Column(String(100))
    template = Column(String(50), nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    message = Column(Text, nullable=True)
    route = Column(String(255), nullable=True)
    action = Column(String(100), nullable=True)
    request_id = Column(String(64), nullable=True)
    upload_id = Column(Integer, ForeignKey("uploads.id", ondelete="SET NULL"), nullable=True)
    run_id = Column(Integer, ForeignKey("analysis_runs.id", ondelete="SET NULL"), nullable=True)
    safe_context_json = Column(Text, default="{}")


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    id = Column(Integer, primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    share_id = Column(Integer, ForeignKey("mentor_shares.id", ondelete="CASCADE"), nullable=True)
    kind = Column(String(100), nullable=False)
    recipient_email = Column(String(255), nullable=False)
    status = Column(String(50), nullable=False)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    sent_at = Column(DateTime, nullable=True)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String(100), primary_key=True)
    value = Column(Text)
