"""
models.py — Verity v2 schema.
Adds: user-definable accounts, quarter/month periods, balance continuity,
document requests with auto-generated references, task assignment (incl. joint
ownership and reassignment), and full change traceability.
"""
from datetime import datetime, date
import json
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

ROLES = ["admin", "lead", "finance_reviewer", "assistant", "viewer"]
ROLE_LABELS = {
    "admin": "Administrator", "lead": "Forensic Lead",
    "finance_reviewer": "Finance Reviewer", "assistant": "Assistant",
    "viewer": "Viewer (read-only)",
}
TASK_STATUS = ["Not started", "In progress", "Blocked", "Done"]
REQ_STATUS = ["Requested", "Chased", "Received", "Accepted", "Rejected", "Unresolved"]
DOC_TYPES = ["Invoice", "Receipt", "Authorisation", "Contract", "Delivery note",
             "Bank advice", "Other"]


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    name = db.Column(db.String(200), nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(30), default="viewer", nullable=False)
    title = db.Column(db.String(120))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw): self.password_hash = generate_password_hash(pw)
    def check_password(self, pw): return check_password_hash(self.password_hash, pw)
    @property
    def is_active(self): return self.active
    @property
    def role_label(self): return ROLE_LABELS.get(self.role, self.role)
    def can(self, *roles): return self.role in roles or self.role == "admin"


class AuditLog(db.Model):
    """Append-only. Never updated or deleted — full traceability of changes."""
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    user_email = db.Column(db.String(200))
    action = db.Column(db.String(120), index=True)
    entity = db.Column(db.String(60))
    entity_id = db.Column(db.String(60))
    before = db.Column(db.Text)
    after = db.Column(db.Text)
    detail = db.Column(db.Text)


class Engagement(db.Model):
    __tablename__ = "engagements"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    client = db.Column(db.String(200))
    code = db.Column(db.String(20), default="SGE")
    period_start = db.Column(db.Date)
    period_end = db.Column(db.Date)
    project_start = db.Column(db.Date)
    project_end = db.Column(db.Date)
    currency = db.Column(db.String(10), default="EGP")
    status = db.Column(db.String(30), default="open")
    settings_json = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def settings(self): return json.loads(self.settings_json or "{}")
    def set_settings(self, d): self.settings_json = json.dumps(d)


class Account(db.Model):
    """Any bank, wallet or ledger source — user-definable, add more at any time."""
    __tablename__ = "accounts"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    code = db.Column(db.String(20))
    name = db.Column(db.String(200))
    kind = db.Column(db.String(20))
    identifier = db.Column(db.String(120))
    currency = db.Column(db.String(10), default="EGP")
    column_map_json = db.Column(db.Text)
    active = db.Column(db.Boolean, default=True)

    @property
    def side(self): return "ledger" if self.kind == "ledger" else "bank"
    def column_map(self): return json.loads(self.column_map_json or "{}")
    def set_column_map(self, d): self.column_map_json = json.dumps(d)


class Period(db.Model):
    """One month, belonging to a quarter. Drives the quarter-by-quarter workflow."""
    __tablename__ = "periods"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    quarter = db.Column(db.String(12), index=True)
    month = db.Column(db.String(7), index=True)
    start = db.Column(db.Date)
    end = db.Column(db.Date)
    status = db.Column(db.String(20), default="Not started")
    signed_off_by = db.Column(db.String(120))
    signed_off_at = db.Column(db.DateTime)


class QuarterFile(db.Model):
    """The written rationale for a quarter — locked on sign-off."""
    __tablename__ = "quarter_files"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    quarter = db.Column(db.String(12), index=True)
    narrative = db.Column(db.Text)
    value_at_risk = db.Column(db.Float, default=0.0)
    locked = db.Column(db.Boolean, default=False)
    signed_off_by = db.Column(db.String(120))
    signed_off_at = db.Column(db.DateTime)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SourceFile(db.Model):
    __tablename__ = "source_files"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    quarter = db.Column(db.String(12))
    filename = db.Column(db.String(300))
    sha256 = db.Column(db.String(64))
    rows_loaded = db.Column(db.Integer, default=0)
    uploaded_by = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)
    account = db.relationship("Account")


class Txn(db.Model):
    __tablename__ = "txns"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), index=True)
    source_file_id = db.Column(db.Integer, db.ForeignKey("source_files.id"))
    side = db.Column(db.String(10), index=True)
    channel = db.Column(db.String(20))
    month = db.Column(db.String(7), index=True)
    quarter = db.Column(db.String(12), index=True)
    date = db.Column(db.Date, index=True)
    txn_type = db.Column(db.String(300))
    description = db.Column(db.String(400))
    counterparty = db.Column(db.String(300))
    counterparty_id = db.Column(db.String(120), index=True)
    currency = db.Column(db.String(10), index=True)     # the transaction's own currency
    amount_in = db.Column(db.Float, default=0.0)        # as stated, in `currency`
    amount_out = db.Column(db.Float, default=0.0)
    fx_rate = db.Column(db.Float)                       # to engagement base currency
    base_in = db.Column(db.Float, default=0.0)          # converted, for reporting only
    base_out = db.Column(db.Float, default=0.0)
    reference = db.Column(db.String(200))
    gl_ref = db.Column(db.String(120))
    matched = db.Column(db.Boolean, default=False, index=True)
    match_tier = db.Column(db.String(40))


class Match(db.Model):
    __tablename__ = "matches"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    quarter = db.Column(db.String(12), index=True)
    month = db.Column(db.String(7), index=True)
    tier = db.Column(db.Integer)
    tier_label = db.Column(db.String(40))
    confidence = db.Column(db.Integer)
    date_gap_days = db.Column(db.Integer)
    amount = db.Column(db.Float)
    currency = db.Column(db.String(10))
    direction = db.Column(db.String(4))
    bank_txn_id = db.Column(db.Integer)
    ledger_txn_id = db.Column(db.Integer)


class Split(db.Model):
    __tablename__ = "splits"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    quarter = db.Column(db.String(12))
    pattern = db.Column(db.String(60))
    amount = db.Column(db.Float)
    direction = db.Column(db.String(4))
    one_txn_id = db.Column(db.Integer)
    many_txn_ids = db.Column(db.Text)
    counterparty = db.Column(db.String(300))


class Balance(db.Model):
    """Opening/closing balance per account per month — continuity checking."""
    __tablename__ = "balances"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), index=True)
    month = db.Column(db.String(7), index=True)
    quarter = db.Column(db.String(12))
    currency = db.Column(db.String(10))
    opening = db.Column(db.Float, default=0.0)
    closing = db.Column(db.Float, default=0.0)
    computed_movement = db.Column(db.Float, default=0.0)
    variance = db.Column(db.Float, default=0.0)
    continuity_gap = db.Column(db.Float, default=0.0)
    anomaly = db.Column(db.String(200))
    entered_by = db.Column(db.String(120))
    account = db.relationship("Account")


class Exception_(db.Model):
    """An unmatched or suspicious item requiring clearance."""
    __tablename__ = "exceptions"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    ref = db.Column(db.String(40), unique=True, index=True)
    quarter = db.Column(db.String(12), index=True)
    month = db.Column(db.String(7))
    category = db.Column(db.String(40), index=True)
    txn_id = db.Column(db.Integer)
    date = db.Column(db.Date)
    counterparty = db.Column(db.String(300))
    amount = db.Column(db.Float)
    currency = db.Column(db.String(10))
    base_amount = db.Column(db.Float)
    detail = db.Column(db.Text)
    status = db.Column(db.String(20), default="Open", index=True)
    resolution = db.Column(db.Text)
    cleared_by = db.Column(db.String(120))
    cleared_at = db.Column(db.DateTime)


class DocRequest(db.Model):
    """A request for supporting documents — emailable/printable memo, auto-referenced."""
    __tablename__ = "doc_requests"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    ref = db.Column(db.String(40), unique=True, index=True)
    exception_id = db.Column(db.Integer, db.ForeignKey("exceptions.id"))
    quarter = db.Column(db.String(12), index=True)
    addressee = db.Column(db.String(200))
    documents_needed = db.Column(db.Text)
    raised_by = db.Column(db.String(120))
    assigned_to_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    raised_at = db.Column(db.DateTime, default=datetime.utcnow)
    due_date = db.Column(db.Date)
    status = db.Column(db.String(20), default="Requested", index=True)
    chased_count = db.Column(db.Integer, default=0)
    last_chased = db.Column(db.Date)
    response_note = db.Column(db.Text)
    closed_at = db.Column(db.DateTime)

    exception = db.relationship("Exception_", backref="requests")
    assignee = db.relationship("User")

    @property
    def overdue(self):
        return bool(self.due_date and self.status in ("Requested", "Chased")
                    and self.due_date < date.today())


class DocumentFile(db.Model):
    __tablename__ = "documents"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    ref = db.Column(db.String(40), unique=True, index=True)
    request_id = db.Column(db.Integer, db.ForeignKey("doc_requests.id"))
    filename = db.Column(db.String(300))
    doc_type = db.Column(db.String(40))
    quarter = db.Column(db.String(12))
    txn_reference = db.Column(db.String(200))
    sha256 = db.Column(db.String(64))
    uploaded_by = db.Column(db.String(200))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)


class FxRate(db.Model):
    """Month-end rate used to express a foreign-currency figure in the base
    currency for reporting. Never used for matching — a USD payment is only ever
    matched against a USD entry."""
    __tablename__ = "fx_rates"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    currency = db.Column(db.String(10), index=True)
    month = db.Column(db.String(7), index=True)
    rate = db.Column(db.Float)          # 1 unit of `currency` = rate x base currency
    source = db.Column(db.String(200))  # where the rate came from — evidence matters
    entered_by = db.Column(db.String(120))
    entered_at = db.Column(db.DateTime, default=datetime.utcnow)


class MappingTemplate(db.Model):
    """A saved column mapping for a statement layout, so the same bank export can
    be loaded month after month without re-mapping it."""
    __tablename__ = "mapping_templates"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    name = db.Column(db.String(150))
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"))
    mapping_json = db.Column(db.Text)
    sample_headers = db.Column(db.Text)
    created_by = db.Column(db.String(120))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    account = db.relationship("Account")

    def mapping(self):
        return json.loads(self.mapping_json or "{}")

    def set_mapping(self, d):
        self.mapping_json = json.dumps(d)


class Task(db.Model):
    """Assignable work item. Supports joint ownership and reassignment."""
    __tablename__ = "tasks"
    id = db.Column(db.Integer, primary_key=True)
    engagement_id = db.Column(db.Integer, db.ForeignKey("engagements.id"), index=True)
    ref = db.Column(db.String(40), index=True)
    title = db.Column(db.String(300))
    detail = db.Column(db.Text)
    phase = db.Column(db.String(40))
    quarter = db.Column(db.String(12))
    owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    joint_owner_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    start_date = db.Column(db.Date)
    due_date = db.Column(db.Date, index=True)
    status = db.Column(db.String(20), default="Not started", index=True)
    progress = db.Column(db.Integer, default=0)
    last_update = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship("User", foreign_keys=[owner_id])
    joint_owner = db.relationship("User", foreign_keys=[joint_owner_id])

    @property
    def overdue(self):
        return bool(self.due_date and self.status != "Done" and self.due_date < date.today())


class TaskUpdate(db.Model):
    """Periodic progress updates against a task."""
    __tablename__ = "task_updates"
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("tasks.id"), index=True)
    ts = db.Column(db.DateTime, default=datetime.utcnow)
    by = db.Column(db.String(120))
    progress = db.Column(db.Integer)
    status = db.Column(db.String(20))
    note = db.Column(db.Text)
