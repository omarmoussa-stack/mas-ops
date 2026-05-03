"""Technician blueprint — mobile-first portal.

Techs only see jobs assigned to them. Financial fields are never exposed.
"""
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, abort
from flask_login import login_required, current_user

from extensions import db
from models import (
    JobRequest,
    STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED,
    notify_admins, NOTIF_INFO, NOTIF_SUCCESS, NOTIF_WARNING,
)

tech_bp = Blueprint("tech", __name__, template_folder="../templates/tech")


def _tech_only():
    if not current_user.is_authenticated:
        abort(401)
    if not (current_user.is_tech or current_user.is_admin):
        abort(403)


def _owned_job_or_404(job_id: int) -> JobRequest:
    job = JobRequest.query.get_or_404(job_id)
    if current_user.is_tech and job.technician_id != current_user.id:
        abort(404)
    return job


@tech_bp.route("/")
@login_required
def dashboard():
    _tech_only()
    query = JobRequest.query
    if current_user.is_tech:
        query = query.filter_by(technician_id=current_user.id)

    active = (
        query.filter(JobRequest.status.in_([STATUS_INCOMPLETE, STATUS_IN_PROCESS]))
        .order_by(JobRequest.expected_date.asc().nullslast())
        .all()
    )

    done_q = (
        JobRequest.query.filter_by(technician_id=current_user.id, status=STATUS_COMPLETED)
        if current_user.is_tech
        else JobRequest.query.filter_by(status=STATUS_COMPLETED)
    )
    done_recent = done_q.order_by(JobRequest.completion_date.desc().nullslast()).limit(5).all()

    return render_template("tech/dashboard.html", active=active, done=done_recent)


@tech_bp.route("/job/<int:job_id>")
@login_required
def job_detail(job_id):
    _tech_only()
    job = _owned_job_or_404(job_id)
    return render_template("tech/job_detail.html", job=job)


@tech_bp.route("/api/job/<int:job_id>/status", methods=["POST"])
@login_required
def api_update_status(job_id):
    _tech_only()
    job = _owned_job_or_404(job_id)

    data = request.get_json(silent=True) or request.form
    new_status = data.get("status")
    if new_status not in (STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED):
        return jsonify(ok=False, error="invalid_status"), 400

    prev_status = job.status
    job.status = new_status
    if new_status == STATUS_COMPLETED:
        job.completion_date = datetime.utcnow()
    else:
        job.completion_date = None

    notes = data.get("tech_notes")
    if notes is not None:
        job.tech_notes = (notes or "").strip() or None

    tech_name = current_user.full_name
    job_label = f"{job.job_type} — {job.client_name} ({job.location})"
    edit_link = url_for("admin.job_edit", job_id=job.id)

    if new_status != prev_status:
        if new_status == STATUS_IN_PROCESS:
            notify_admins(f"بدأ {tech_name} العمل على: {job_label}", link=edit_link, type=NOTIF_WARNING)
        elif new_status == STATUS_COMPLETED:
            notify_admins(f"أكمل {tech_name} المهمة: {job_label}", link=edit_link, type=NOTIF_SUCCESS)
        elif new_status == STATUS_INCOMPLETE:
            notify_admins(f"أعاد {tech_name} المهمة إلى غير مكتملة: {job_label}", link=edit_link, type=NOTIF_WARNING)

    if notes and notes.strip():
        notify_admins(f"أضاف {tech_name} ملاحظات على: {job_label}", link=edit_link, type=NOTIF_INFO)

    db.session.commit()
    return jsonify(ok=True, job=job.to_tech_dict())
