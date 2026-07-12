"""SQLAlchemy ORM models for worldquant-harness."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)  # bcrypt, NULL=未设置密码
    nickname = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    subscribe_weekly = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    sessions = relationship("Session", back_populates="user", lazy="selectin")
    tasks = relationship("Task", back_populates="user", lazy="selectin")
    reports = relationship("Report", back_populates="user", lazy="selectin")


class VerificationCode(Base):
    __tablename__ = "verification_codes"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    email = Column(String(255), nullable=False, index=True)
    code = Column(String(6), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    used = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_verification_codes_email_used", "email", "used"),
    )


class Session(Base):
    __tablename__ = "sessions"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    name = Column(String(200), nullable=True)
    market = Column(String(20), default="a_share", nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User", back_populates="sessions")
    tasks = relationship("Task", back_populates="session", lazy="selectin")


class Task(Base):
    __tablename__ = "tasks"

    id = Column(String(12), primary_key=True)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    session_id = Column(Uuid, ForeignKey("sessions.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False, default="pending")
    task_type = Column(String(50), nullable=True, default="backtest")
    parent_task_id = Column(String(12), ForeignKey("tasks.id"), nullable=True)
    params = Column(JSON, nullable=True)
    expression = Column(Text, nullable=True)
    result = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User", back_populates="tasks")
    session = relationship("Session", back_populates="tasks")
    reports = relationship("Report", back_populates="task", lazy="selectin")


class Report(Base):
    __tablename__ = "reports"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String(12), ForeignKey("tasks.id"), nullable=False)
    filename = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User", back_populates="reports")
    task = relationship("Task", back_populates="reports")


class SavedFactor(Base):
    __tablename__ = "saved_factors"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(String(12), ForeignKey("tasks.id"), nullable=True)
    expression = Column(Text, nullable=False)
    name = Column(String(200), nullable=True)       # 用户自定义名称
    note = Column(Text, nullable=True)              # 备注
    tags = Column(JSON, nullable=True)              # 标签列表
    metrics = Column(JSON, nullable=True)           # 快照：report_metrics
    backtest_summary = Column(JSON, nullable=True)  # 快照：backtest_summary
    params = Column(JSON, nullable=True)            # 回测参数
    report_url = Column(String(500), nullable=True)
    market = Column(String(20), default="a_share", nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User")


class Feedback(Base):
    __tablename__ = "feedbacks"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    screenshot_path = Column(String(500), nullable=True)
    task_id = Column(String(12), nullable=True)
    user_agent = Column(String(500), nullable=True)
    page_url = Column(String(500), nullable=True)
    webhook_sent = Column(Boolean, default=False, nullable=False)
    resolved = Column(Boolean, default=False, nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User")


class SubmittedAlpha(Base):
    __tablename__ = "submitted_alphas"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    alpha_id = Column(String(50), nullable=False, index=True)
    expression = Column(Text, nullable=False)
    expression_normalized = Column(Text, nullable=True)
    region = Column(String(10), nullable=False, default="USA")
    universe = Column(String(20), nullable=False, default="TOP3000")
    delay = Column(Integer, nullable=False, default=1)
    decay = Column(Integer, nullable=False, default=0)
    neutralization = Column(String(30), nullable=False, default="SUBINDUSTRY")
    truncation = Column(Float, nullable=False, default=0.08)
    tag = Column(String(100), nullable=True)
    sharpe = Column(Float, nullable=True)
    fitness = Column(Float, nullable=True)
    returns = Column(Float, nullable=True)
    turnover = Column(Float, nullable=True)
    status = Column(String(20), nullable=False, default="submitted")
    submitted_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("ix_submitted_alphas_user_expr", "user_id", "expression_normalized"),
    )


class WQAlphaExperiment(Base):
    __tablename__ = "wq_alpha_experiments"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    alpha_id = Column(String(50), nullable=True, index=True)
    expression = Column(Text, nullable=False)
    expression_normalized = Column(Text, nullable=False)
    expression_hash = Column(String(64), nullable=False, index=True)
    params_hash = Column(String(64), nullable=False, index=True)

    account = Column(String(50), nullable=False, default="primary")
    region = Column(String(10), nullable=False, default="USA")
    universe = Column(String(20), nullable=False, default="TOP3000")
    delay = Column(Integer, nullable=False, default=1)
    decay = Column(Integer, nullable=False, default=0)
    neutralization = Column(String(30), nullable=False, default="SUBINDUSTRY")
    truncation = Column(Float, nullable=False, default=0.08)

    source_type = Column(String(50), nullable=True)
    source_family = Column(String(100), nullable=True)
    source_run_id = Column(String(200), nullable=True, index=True)
    source_file = Column(String(500), nullable=True)
    source_tag = Column(String(100), nullable=True)
    parent_experiment_id = Column(Uuid, nullable=True)
    candidate_meta = Column(JSON, nullable=True)

    lifecycle_status = Column(String(40), nullable=False, default="candidate", index=True)
    submit_eligible = Column(Boolean, nullable=True)
    non_correlation_pass = Column(Boolean, nullable=True)
    api_check_status = Column(String(50), nullable=True, index=True)
    platform_status = Column(String(50), nullable=True)
    review_failure_kind = Column(String(50), nullable=True)

    sharpe = Column(Float, nullable=True)
    fitness = Column(Float, nullable=True, index=True)
    returns = Column(Float, nullable=True)
    turnover = Column(Float, nullable=True)
    drawdown = Column(Float, nullable=True)
    margin = Column(Float, nullable=True)
    long_count = Column(Integer, nullable=True)
    short_count = Column(Integer, nullable=True)
    grade = Column(String(30), nullable=True)

    self_correlation_result = Column(String(30), nullable=True)
    self_correlation_value = Column(Float, nullable=True)
    self_correlation_limit = Column(Float, nullable=True)
    prod_correlation_result = Column(String(30), nullable=True)
    prod_correlation_value = Column(Float, nullable=True)
    prod_correlation_limit = Column(Float, nullable=True)

    max_similarity_to_blocked = Column(Float, nullable=True)
    max_similarity_to_hits = Column(Float, nullable=True)
    nearest_blocked_alpha_id = Column(String(50), nullable=True)
    nearest_blocked_expression = Column(Text, nullable=True)
    nearest_blocked_source = Column(String(100), nullable=True)
    similarity_details = Column(JSON, nullable=True)

    failure_kind = Column(String(50), nullable=True, index=True)
    failure_reasons = Column(JSON, nullable=True)
    raw_result = Column(JSON, nullable=True)
    raw_api_check = Column(JSON, nullable=True)

    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User")

    __table_args__ = (
        Index("ix_wq_alpha_experiments_expr_params_run", "expression_hash", "params_hash", "source_run_id"),
        Index("ix_wq_alpha_experiments_status_fitness", "lifecycle_status", "fitness"),
        Index("ix_wq_alpha_experiments_source_family", "source_family", "created_at"),
    )


class WQFailureMemory(Base):
    __tablename__ = "wq_failure_memory"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    experiment_id = Column(Uuid, nullable=True, index=True)

    memory_type = Column(String(40), nullable=False, index=True)
    scope = Column(String(100), nullable=False, default="global")
    expression = Column(Text, nullable=True)
    expression_normalized = Column(Text, nullable=True)
    expression_hash = Column(String(64), nullable=True, index=True)
    pattern_signature = Column(String(500), nullable=True, index=True)
    fields = Column(JSON, nullable=True)
    operators = Column(JSON, nullable=True)
    params = Column(JSON, nullable=True)

    failure_kind = Column(String(50), nullable=False, index=True)
    severity = Column(String(20), nullable=False, default="note", index=True)
    confidence = Column(Float, nullable=False, default=1.0)
    evidence_count = Column(Integer, nullable=False, default=1)
    evidence = Column(JSON, nullable=True)
    source_experiment_ids = Column(JSON, nullable=True)

    first_seen_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    last_seen_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    user = relationship("User")

    __table_args__ = (
        Index("ix_wq_failure_memory_kind_severity", "failure_kind", "severity"),
        Index("ix_wq_failure_memory_type_kind", "memory_type", "failure_kind", "severity"),
    )


class WQAgentEvent(Base):
    """Append-only canonical lifecycle event for the WQ agent v2 core."""

    __tablename__ = "wq_agent_events"

    event_id = Column(String(48), primary_key=True)
    schema_version = Column(Integer, nullable=False, default=2)
    event_type = Column(String(50), nullable=False, index=True)
    occurred_at = Column(DateTime(timezone=True), nullable=False)
    run_id = Column(String(200), nullable=False, index=True)
    attempt_uid = Column(String(64), nullable=False, index=True)
    candidate_uid = Column(String(64), nullable=False, index=True)
    scope_key = Column(String(64), nullable=False, index=True)
    owner_key = Column(String(100), nullable=False, default="local", index=True)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    account = Column(String(50), nullable=False, default="primary")
    region = Column(String(10), nullable=False, default="USA")
    universe = Column(String(20), nullable=False, default="TOP3000")
    delay = Column(Integer, nullable=False, default=1)
    alpha_id = Column(String(50), nullable=True, index=True)
    stage = Column(String(50), nullable=False)
    payload = Column(JSON, nullable=False, default=dict)
    source_artifact = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_wq_agent_events_scope_candidate", "scope_key", "candidate_uid"),
        Index("ix_wq_agent_events_run_attempt", "run_id", "attempt_uid"),
    )


class WQCandidateState(Base):
    """Current scoped projection rebuilt from canonical agent events."""

    __tablename__ = "wq_candidate_states"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    scope_key = Column(String(64), nullable=False, index=True)
    owner_key = Column(String(100), nullable=False, default="local", index=True)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    account = Column(String(50), nullable=False, default="primary")
    region = Column(String(10), nullable=False, default="USA")
    universe = Column(String(20), nullable=False, default="TOP3000")
    delay = Column(Integer, nullable=False, default=1)
    candidate_uid = Column(String(64), nullable=False, index=True)
    expression = Column(Text, nullable=False)
    expression_normalized = Column(Text, nullable=False)
    expression_hash = Column(String(64), nullable=False, index=True)
    settings_hash = Column(String(64), nullable=False, index=True)
    effective_settings = Column(JSON, nullable=False, default=dict)
    run_id = Column(String(200), nullable=False, index=True)
    attempt_uid = Column(String(64), nullable=False, index=True)
    alpha_id = Column(String(50), nullable=True, index=True)
    lifecycle_status = Column(String(50), nullable=False, default="candidate", index=True)
    revision = Column(Integer, nullable=False, default=0)
    metrics = Column(JSON, nullable=False, default=dict)
    correlation = Column(JSON, nullable=False, default=dict)
    failure = Column(JSON, nullable=False, default=dict)
    source_meta = Column(JSON, nullable=False, default=dict)
    latest_event_id = Column(String(48), nullable=False)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False)

    __table_args__ = (
        Index("uq_wq_candidate_states_scope_uid", "scope_key", "candidate_uid", unique=True),
        Index("ix_wq_candidate_states_scope_status", "scope_key", "lifecycle_status"),
    )


class WQMemoryItem(Base):
    """Scoped long-term memory projection with evidence provenance."""

    __tablename__ = "wq_memory_items"

    memory_id = Column(String(64), primary_key=True)
    scope_key = Column(String(64), nullable=False, index=True)
    owner_key = Column(String(100), nullable=False, default="local", index=True)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=True, index=True)
    account = Column(String(50), nullable=False, default="primary")
    region = Column(String(10), nullable=False, default="USA")
    universe = Column(String(20), nullable=False, default="TOP3000")
    delay = Column(Integer, nullable=False, default=1)
    memory_key = Column(String(200), nullable=False)
    memory_kind = Column(String(50), nullable=False, index=True)
    subject_key = Column(String(200), nullable=False, index=True)
    candidate_uid = Column(String(64), nullable=True, index=True)
    failure_kind = Column(String(50), nullable=True, index=True)
    severity = Column(String(20), nullable=False, default="note")
    evidence_class = Column(String(40), nullable=False, index=True)
    polarity = Column(String(20), nullable=False, default="negative")
    confidence = Column(Float, nullable=False, default=0.5)
    support_count = Column(Integer, nullable=False, default=1)
    contradiction_count = Column(Integer, nullable=False, default=0)
    state = Column(String(20), nullable=False, default="active", index=True)
    payload = Column(JSON, nullable=False, default=dict)
    evidence_event_ids = Column(JSON, nullable=False, default=list)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)
    valid_until = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("uq_wq_memory_items_scope_key", "scope_key", "memory_key", unique=True),
        Index("ix_wq_memory_items_scope_kind", "scope_key", "memory_kind", "state"),
    )


class DailySummary(Base):
    __tablename__ = "daily_summaries"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    date = Column(String(10), nullable=False)          # "2026-03-24"
    market = Column(String(20), default="a_share", nullable=False)
    title = Column(String(200), nullable=True)
    content = Column(Text, nullable=True)              # markdown
    metrics = Column(JSON, nullable=True)              # index changes, volume, etc.
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    __table_args__ = (
        Index("ix_daily_summaries_date_market", "date", "market", unique=True),
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id = Column(Uuid, ForeignKey("users.id"), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False, unique=True)
    prefix = Column(String(10), nullable=False)
    name = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow, nullable=False)

    user = relationship("User")
