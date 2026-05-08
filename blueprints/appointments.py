"""Appointments blueprint — manage site visits before they become jobs."""

from __future__ import annotations
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import (
    Blueprint, render_template, request,
    redirect, url_for, flash, abort,
)
from flask_login import current_user, login_required

from extensions import db
from models import (
    Client, JobRequest, User,
    STATUS_VISIT, STATUS_INCOMPLETE,
    ROLE_TECH,
    notify, notify_admins, NOTIF_INFO, NOTIF_SUCCESS,
)

appointments_bp = Blueprint("appointments", __name__, template_folder="../templates")

# ---------------------------------------------------------------------------
# Arabic helpers
# ---------------------------------------------------------------------------
AR_DAYS = {
    0:"الاثنين", 1:"الثلاثاء", 2:"الأربعاء",
    3:"الخميس",  4:"الجمعة",   5:"السبت",    6:"الأحد"
}
AR_MONTHS = {
    1:"يناير",  2:"فبراير", 3:"مارس",    4:"أبريل",
    5:"مايو",   6:"يونيو",  7:"يوليو",   8:"أغسطس",
    9:"سبتمبر", 10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"
}
AR_TYPES = {
    "Shutter Maintenance":   "صيانة شتر",
    "Shutter Installation":  "تركيب شتر",
    "Aluminum Installation": "تركيب ألمونيوم",
    "Aluminum Repair":       "إصلاح ألمونيوم",
    "Inspection":            "معاينة",
    "Other":                 "أعمال متنوعة",
}

def _fmt_hour(h):
    h12    = h % 12 or 12
    suffix = "صباحاً" if h < 12 else ("ظهراً" if h < 13 else "مساءً")
    return f"{h12} {suffix}"

def _english_date_range(dt):
    EN_DAYS   = {0:"Monday",1:"Tuesday",2:"Wednesday",3:"Thursday",4:"Friday",5:"Saturday",6:"Sunday"}
    EN_MONTHS = {1:"January",2:"February",3:"March",4:"April",5:"May",6:"June",
                 7:"July",8:"August",9:"September",10:"October",11:"November",12:"December"}
    def fmt_12h(h):
        suffix = "AM" if h < 12 else "PM"
        h12    = h % 12 or 12
        return f"{h12}:00 {suffix}"
    return (
        f"{EN_DAYS[dt.weekday()]} {dt.day} {EN_MONTHS[dt.month]} {dt.year}, "
        f"between {fmt_12h(dt.hour)} and {fmt_12h(dt.hour + 2)}"
    )

def _format_phone(raw):
    phone = "".join(c for c in (raw or "") if c.isdigit())
    if phone.startswith("0"):
        phone = "20" + phone[1:]
    elif not phone.startswith("20") and len(phone) == 10:
        phone = "20" + phone
    return phone

# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------
def admin_required(view_fn):
    @wraps(view_fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view_fn(*args, **kwargs)
    return wrapper

# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------
@appointments_bp.route("/")
@admin_required
def list_appointments():
    tech_id   = request.args.get("tech_id", type=int)
    date_from = request.args.get("date_from", "")
    date_to   = request.args.get("date_to", "")

    query = JobRequest.query.filter_by(status=STATUS_VISIT, is_archived=False)

    if tech_id:
        query = query.filter(JobRequest.technician_id == tech_id)
    if date_from:
        try:
            query = query.filter(JobRequest.expected_date >= datetime.fromisoformat(date_from))
        except ValueError:
            pass
    if date_to:
        try:
            query = query.filter(
                JobRequest.expected_date <= datetime.fromisoformat(date_to + "T23:59:59")
            )
        except ValueError:
            pass

    visits = query.order_by(JobRequest.expected_date.asc().nullslast()).all()
    techs  = User.query.filter_by(role=ROLE_TECH, is_active_flag=True).all()

    return render_template(
        "admin/appointments.html",
        visits=visits, techs=techs,
        tech_id=tech_id, date_from=date_from, date_to=date_to,
        now=datetime.utcnow(),
    )

# ---------------------------------------------------------------------------
# New visit
# ---------------------------------------------------------------------------
@appointments_bp.route("/new", methods=["GET", "POST"])
@admin_required
def appointment_new():
    techs   = User.query.filter_by(role=ROLE_TECH, is_active_flag=True).all()
    clients = Client.query.order_by(Client.name).all()

    if request.method == "POST":
        form      = request.form
        client_id = form.get("client_id", type=int)
        client    = Client.query.get(client_id) if client_id else None

        visit = JobRequest(
            client_id   = client_id,
            client_name = client.name  if client else (form.get("client_name") or "").strip(),
            phone       = client.phone if client else (form.get("phone") or "").strip(),
            location    = (form.get("location") or (client.location if client else "") or "").strip() or "Other",
            address     = (form.get("address")  or (client.address  if client else "") or "").strip() or None,
            job_type    = (form.get("job_type")  or "").strip(),
            description = (form.get("description") or "").strip() or None,
            status      = STATUS_VISIT,
            confirmed   = False,
        )
        tech_id = form.get("technician_id", type=int)
        visit.technician_id = tech_id or None

        expected = form.get("expected_date")
        if expected:
            try:
                visit.expected_date = datetime.fromisoformat(expected)
            except ValueError:
                pass

        db.session.add(visit)
        db.session.flush()

        if visit.technician_id:
            notify(
                visit.technician_id,
                f"📅 زيارة جديدة: {visit.job_type} — {visit.client_name} ({visit.location})",
                link=url_for("tech.job_detail", job_id=visit.id),
                type=NOTIF_INFO,
            )

        db.session.commit()
        flash(f"تم حجز الزيارة #{visit.id} بنجاح.", "success")
        return redirect(url_for("appointments.list_appointments"))

    return render_template("admin/appointment_form.html", techs=techs, clients=clients)

# ---------------------------------------------------------------------------
# WhatsApp — casual Arabic message, no magic links
# ---------------------------------------------------------------------------
@appointments_bp.route("/<int:visit_id>/whatsapp-confirm")
@admin_required
def whatsapp_confirm(visit_id):
    visit       = JobRequest.query.get_or_404(visit_id)
    date_str    = _english_date_range(visit.expected_date) if visit.expected_date else "سيتم تحديد الموعد"
    job_type_ar = AR_TYPES.get(visit.job_type, visit.job_type)

    msg = "\n".join([
        f"Dear {visit.client_name},",
        "",
        f"We would like to confirm our appointment with you on {date_str}.",
        "",
        "Please confirm.",
        "",
        "Best Regards,",
        "MAS — Moussa for Aluminium Solutions",
    ])

    return redirect(f"https://wa.me/{_format_phone(visit.phone)}?text={quote(msg)}")

# ---------------------------------------------------------------------------
# Option C — Admin manually marks as confirmed
# ---------------------------------------------------------------------------
@appointments_bp.route("/<int:visit_id>/confirm", methods=["POST"])
@admin_required
def manual_confirm(visit_id):
    visit           = JobRequest.query.get_or_404(visit_id)
    visit.confirmed = True
    db.session.commit()
    flash(f"✅ تم تأكيد موعد {visit.client_name}.", "success")
    return redirect(url_for("appointments.list_appointments"))

# ---------------------------------------------------------------------------
# Convert visit → job
# ---------------------------------------------------------------------------
@appointments_bp.route("/<int:visit_id>/convert", methods=["POST"])
@admin_required
def convert_to_job(visit_id):
    visit        = JobRequest.query.get_or_404(visit_id)
    visit.status = STATUS_INCOMPLETE
    db.session.commit()
    flash(f"تم تحويل الزيارة #{visit_id} إلى مهمة! ✅", "success")
    return redirect(url_for("admin.jobs_list"))

# ---------------------------------------------------------------------------
# Cancel visit
# ---------------------------------------------------------------------------
@appointments_bp.route("/<int:visit_id>/cancel", methods=["POST"])
@admin_required
def cancel_visit(visit_id):
    visit             = JobRequest.query.get_or_404(visit_id)
    visit.is_archived = True
    db.session.commit()
    flash(f"تم إلغاء الزيارة #{visit_id}.", "info")
    return redirect(url_for("appointments.list_appointments"))
