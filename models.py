"""SQLAlchemy models for the MAS Ops system.

Entities
--------
- User        : Admin (management) or Tech (field technician). Flask-Login compatible.
- Client      : A customer. One client -> many JobRequests.
- JobRequest  : A scheduled customer job. Financial fields are admin-only.
- Notification: In-app bell notification.
"""
from __future__ import annotations

from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

from extensions import db, login_manager


# ---------------------------------------------------------------------------
# Role constants
# ---------------------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_TECH  = "tech"

STATUS_VISIT      = "Visit"
STATUS_INCOMPLETE = "Incomplete"
STATUS_IN_PROCESS = "In Process"
STATUS_COMPLETED  = "Completed"

STATUS_COLORS = {
    STATUS_VISIT:      "#6f42c1",
    STATUS_INCOMPLETE: "#0d6efd",
    STATUS_IN_PROCESS: "#ffc107",
    STATUS_COMPLETED:  "#198754",
}


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------
class User(UserMixin, db.Model):
    __tablename__ = "users"

    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(64), unique=True, nullable=False, index=True)
    password_hash  = db.Column(db.String(255), nullable=False)
    full_name      = db.Column(db.String(120), nullable=False)
    role           = db.Column(db.String(16), nullable=False, default=ROLE_TECH)
    is_active_flag = db.Column(db.Boolean, default=True, nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    jobs = db.relationship(
        "JobRequest",
        backref="technician",
        lazy="dynamic",
        foreign_keys="JobRequest.technician_id",
    )

    def set_password(self, raw_password: str) -> None:
        self.password_hash = generate_password_hash(raw_password, method="pbkdf2:sha256")

    def check_password(self, raw_password: str) -> bool:
        return check_password_hash(self.password_hash, raw_password)

    @property
    def is_admin(self) -> bool:
        return self.role == ROLE_ADMIN

    @property
    def is_tech(self) -> bool:
        return self.role == ROLE_TECH

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role})>"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------
class Client(db.Model):
    __tablename__ = "clients"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(120), nullable=False, index=True)
    phone      = db.Column(db.String(32),  nullable=False, index=True)
    location   = db.Column(db.String(64),  nullable=True)
    address    = db.Column(db.String(255), nullable=True)
    notes      = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    jobs = db.relationship(
        "JobRequest",
        backref="client",
        lazy="dynamic",
        foreign_keys="JobRequest.client_id",
    )

    @property
    def total_jobs(self) -> int:
        return self.jobs.count()

    @property
    def completed_jobs(self) -> int:
        return self.jobs.filter_by(status=STATUS_COMPLETED).count()

    @property
    def total_revenue(self) -> float:
        rows = (
            self.jobs
            .filter_by(status=STATUS_COMPLETED)
            .with_entities(JobRequest.amount)
            .all()
        )
        return sum(r.amount for r in rows if r.amount is not None)

    @property
    def last_job_date(self):
        latest = self.jobs.order_by(JobRequest.created_at.desc()).first()
        return latest.created_at if latest else None

    @property
    def usual_technician(self):
        from sqlalchemy import func
        row = (
            db.session.query(
                JobRequest.technician_id,
                func.count(JobRequest.id).label("cnt"),
            )
            .filter(
                JobRequest.client_id == self.id,
                JobRequest.technician_id.isnot(None),
            )
            .group_by(JobRequest.technician_id)
            .order_by(func.count(JobRequest.id).desc())
            .first()
        )
        return User.query.get(row.technician_id) if row else None

    @property
    def initials(self) -> str:
        parts = self.name.strip().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.name[:2].upper()

    def to_search_dict(self) -> dict:
        return {
            "id":       self.id,
            "name":     self.name,
            "phone":    self.phone,
            "location": self.location or "",
            "address":  self.address  or "",
        }

    def __repr__(self) -> str:
        return f"<Client #{self.id} {self.name}>"


# ---------------------------------------------------------------------------
# JobRequest
# ---------------------------------------------------------------------------
class JobRequest(db.Model):
    __tablename__ = "job_requests"

    id = db.Column(db.Integer, primary_key=True)

    # Client registry link (nullable — legacy rows have no client_id)
    client_id = db.Column(
        db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True
    )

    # Denormalised fallbacks (always populated — used by tech portal & ledger sync)
    client_name = db.Column(db.String(120), nullable=False)
    phone       = db.Column(db.String(32),  nullable=False)
    location    = db.Column(db.String(64),  nullable=False)
    address     = db.Column(db.String(255), nullable=True)

    job_type    = db.Column(db.String(64), nullable=False)
    description = db.Column(db.Text, nullable=True)

    technician_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=True, index=True
    )

    status          = db.Column(db.String(16), nullable=False, default=STATUS_INCOMPLETE, index=True)
    expected_date   = db.Column(db.DateTime, nullable=True, index=True)
    completion_date = db.Column(db.DateTime, nullable=True)

    # Financial — ADMIN ONLY
    amount        = db.Column(db.Float,   nullable=True)
    invoiced      = db.Column(db.Boolean, default=False, nullable=False)
    invoice_items = db.Column(db.Text,    nullable=True)

    tech_notes  = db.Column(db.Text, nullable=True)
    is_archived     = db.Column(db.Boolean, default=False, nullable=False, index=True)
    confirmed       = db.Column(db.Boolean, default=False, nullable=False)
    confirm_token   = db.Column(db.String(64), nullable=True, unique=True, index=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def to_calendar_event(self, include_amount: bool = False) -> dict:
        payload = {
            "id":              self.id,
            "title":           f"{self.job_type} — {self.client_name}",
            "start":           self.expected_date.isoformat() if self.expected_date else None,
            "allDay":          False,
            "backgroundColor": STATUS_COLORS.get(self.status, "#6c757d"),
            "borderColor":     STATUS_COLORS.get(self.status, "#6c757d"),
            "extendedProps": {
                "status":      self.status,
                "location":    self.location,
                "client_name": self.client_name,
                "client_id":   self.client_id,
                "phone":       self.phone,
                "job_type":    self.job_type,
                "technician":  self.technician.full_name if self.technician else None,
            },
        }
        if include_amount:
            payload["extendedProps"]["amount"] = self.amount
        return payload

    def to_tech_dict(self) -> dict:
        return {
            "id":            self.id,
            "client_name":   self.client_name,
            "phone":         self.phone,
            "location":      self.location,
            "address":       self.address,
            "job_type":      self.job_type,
            "description":   self.description,
            "status":        self.status,
            "expected_date": self.expected_date.isoformat() if self.expected_date else None,
            "tech_notes":    self.tech_notes,
        }

    def __repr__(self) -> str:
        return f"<JobRequest #{self.id} {self.client_name} [{self.status}]>"


# ---------------------------------------------------------------------------
# Notification
# ---------------------------------------------------------------------------
NOTIF_INFO    = "info"
NOTIF_SUCCESS = "success"
NOTIF_WARNING = "warning"


class Notification(db.Model):
    __tablename__ = "notifications"

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    message    = db.Column(db.String(255), nullable=False)
    link       = db.Column(db.String(255), nullable=True)
    type       = db.Column(db.String(16),  nullable=False, default=NOTIF_INFO)
    is_read    = db.Column(db.Boolean, default=False, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    recipient = db.relationship("User", backref=db.backref("notifications", lazy="dynamic"))

    def to_dict(self):
        return {
            "id":         self.id,
            "message":    self.message,
            "link":       self.link,
            "type":       self.type,
            "is_read":    self.is_read,
            "created_at": self.created_at.strftime("%d %b, %H:%M"),
        }

    def __repr__(self):
        return f"<Notification #{self.id} -> user {self.user_id}>"


def notify(user_id, message, link=None, type=NOTIF_INFO):
    db.session.add(Notification(user_id=user_id, message=message, link=link, type=type))


def notify_admins(message, link=None, type=NOTIF_INFO):
    for admin in User.query.filter_by(role=ROLE_ADMIN, is_active_flag=True).all():
        notify(admin.id, message, link=link, type=type)


@login_manager.user_loader
def load_user(user_id: str):
    return User.query.get(int(user_id))
