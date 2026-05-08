"""Admin blueprint — dashboard, calendar, job CRUD, invoices, user management.

Every route is gated by admin_required.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import wraps

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, jsonify, send_file,
)
from flask_login import current_user, login_required

from extensions import db
from models import (
    Client, JobRequest, User,
    ROLE_ADMIN, ROLE_TECH,
    STATUS_VISIT, STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED,
    notify, notify_admins, NOTIF_SUCCESS, NOTIF_INFO,
)

admin_bp = Blueprint("admin", __name__, template_folder="templates/admin")


def admin_required(view_fn):
    @wraps(view_fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view_fn(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@admin_bp.route("/")
@admin_required
def dashboard():
    stats = {
        "visits":          JobRequest.query.filter_by(status=STATUS_VISIT,      is_archived=False).count(),
        "incomplete":      JobRequest.query.filter_by(status=STATUS_INCOMPLETE, is_archived=False).count(),
        "in_process":      JobRequest.query.filter_by(status=STATUS_IN_PROCESS, is_archived=False).count(),
        "completed":       JobRequest.query.filter_by(status=STATUS_COMPLETED,  is_archived=False).count(),
        "pending_invoices": JobRequest.query.filter_by(
            status=STATUS_COMPLETED, invoiced=False, is_archived=False
        ).count(),
        "total_clients":   Client.query.count(),
    }
    recent = JobRequest.query.filter_by(is_archived=False).order_by(JobRequest.created_at.desc()).limit(10).all()
    return render_template("admin/dashboard.html", stats=stats, recent=recent)


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------
@admin_bp.route("/calendar")
@admin_required
def calendar():
    techs = User.query.filter_by(role=ROLE_TECH, is_active_flag=True).all()
    return render_template("admin/calendar.html", techs=techs)


# ---------------------------------------------------------------------------
# Jobs: list + create + edit + delete
# ---------------------------------------------------------------------------
@admin_bp.route("/jobs")
@admin_required
def jobs_list():
    status = request.args.get("status")
    query = JobRequest.query.filter_by(is_archived=False)
    if status in (STATUS_VISIT, STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED):
        query = query.filter_by(status=status)
    jobs = query.order_by(JobRequest.expected_date.desc().nullslast()).all()
    return render_template("admin/jobs_list.html", jobs=jobs, status_filter=status)


@admin_bp.route("/jobs/new", methods=["GET", "POST"])
@admin_required
def job_new():
    techs = User.query.filter_by(role=ROLE_TECH, is_active_flag=True).all()
    if request.method == "POST":
        job = _populate_job_from_form(JobRequest(), request.form)
        db.session.add(job)
        db.session.flush()
        if job.technician_id:
            notify(
                job.technician_id,
                f"تم تعيين مهمة جديدة لك: {job.job_type} — {job.client_name} ({job.location})",
                link=url_for("tech.job_detail", job_id=job.id),
                type=NOTIF_INFO,
            )
        db.session.commit()
        flash(f"Job #{job.id} created.", "success")
        return redirect(url_for("admin.jobs_list"))
    return render_template("admin/job_form.html", job=None, techs=techs)


@admin_bp.route("/jobs/<int:job_id>/edit", methods=["GET", "POST"])
@admin_required
def job_edit(job_id):
    job = JobRequest.query.get_or_404(job_id)
    techs = User.query.filter_by(role=ROLE_TECH, is_active_flag=True).all()
    if request.method == "POST":
        old_tech_id = job.technician_id
        _populate_job_from_form(job, request.form)
        if job.technician_id and job.technician_id != old_tech_id:
            notify(
                job.technician_id,
                f"تم تحويل مهمة إليك: {job.job_type} — {job.client_name} ({job.location})",
                link=url_for("tech.job_detail", job_id=job.id),
                type=NOTIF_INFO,
            )
        db.session.commit()
        flash(f"Job #{job.id} updated.", "success")
        return redirect(url_for("admin.jobs_list"))
    return render_template("admin/job_form.html", job=job, techs=techs)


@admin_bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
@admin_required
def job_delete(job_id):
    """Soft delete — marks the job as archived."""
    print(f"\n=== DELETE ROUTE HIT for job_id={job_id} ===")
    print(f"Method: {request.method}")
    print(f"Form data: {dict(request.form)}")

    job = JobRequest.query.get_or_404(job_id)
    print(f"Found job: #{job.id} {job.client_name}, is_archived={job.is_archived}")

    try:
        job.is_archived = True
        db.session.commit()
        print(f"SUCCESS: job.is_archived is now {job.is_archived}")
        flash(f"Job #{job_id} ({job.client_name}) moved to archive.", "info")
    except Exception as e:
        db.session.rollback()
        print(f"ERROR: {e}")
        flash(f"Could not archive job #{job_id}: {str(e)}", "danger")

    return redirect(url_for("admin.jobs_list"))


@admin_bp.route("/archive")
@admin_required
def archive():
    tab = request.args.get("tab", "archived")
    client_filter = request.args.get("client", "").strip()

    if tab == "completed":
        query = JobRequest.query.filter_by(status=STATUS_COMPLETED, is_archived=False)
    else:
        query = JobRequest.query.filter_by(is_archived=True)

    if client_filter:
        query = query.filter(JobRequest.client_name.ilike(f"%{client_filter}%"))

    jobs = query.order_by(JobRequest.updated_at.desc()).all()

    counts = {
        "archived":  JobRequest.query.filter_by(is_archived=True).count(),
        "completed": JobRequest.query.filter_by(status=STATUS_COMPLETED, is_archived=False).count(),
    }

    return render_template(
        "admin/archive.html",
        jobs=jobs, tab=tab, counts=counts, client_filter=client_filter,
    )


@admin_bp.route("/archive/<int:job_id>/restore", methods=["POST"])
@admin_required
def archive_restore(job_id):
    job = JobRequest.query.get_or_404(job_id)
    try:
        job.is_archived = False
        db.session.commit()
        flash(f"Job #{job_id} ({job.client_name}) restored from archive.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Could not restore job #{job_id}: {str(e)}", "danger")
    return redirect(url_for("admin.archive"))


@admin_bp.route("/archive/<int:job_id>/destroy", methods=["POST"])
@admin_required
def archive_destroy(job_id):
    job = JobRequest.query.get_or_404(job_id)
    try:
        client_name = job.client_name
        from models import Notification
        Notification.query.filter(
            Notification.link.like(f"%/jobs/{job_id}%")
        ).delete(synchronize_session=False)
        db.session.delete(job)
        db.session.commit()
        flash(f"Job #{job_id} ({client_name}) permanently deleted.", "info")
    except Exception as e:
        db.session.rollback()
        flash(f"Could not permanently delete job #{job_id}: {str(e)}", "danger")
    return redirect(url_for("admin.archive"))


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------
@admin_bp.route("/invoices")
@admin_required
def invoices():
    pending = (
        JobRequest.query.filter_by(status=STATUS_COMPLETED, invoiced=False, is_archived=False)
        .order_by(JobRequest.completion_date.desc().nullslast())
        .all()
    )
    client_filter = request.args.get("client", "").strip()
    tab = request.args.get("tab", "pending")
    history_query = JobRequest.query.filter_by(invoiced=True, is_archived=False)
    if client_filter:
        history_query = history_query.filter(
            JobRequest.client_name.ilike(f"%{client_filter}%")
        )
    history = history_query.order_by(JobRequest.completion_date.desc().nullslast()).all()
    return render_template(
        "admin/invoices.html",
        pending=pending, history=history,
        tab=tab, client_filter=client_filter,
    )


@admin_bp.route("/invoices/<int:job_id>")
@admin_required
def invoice_view(job_id):
    job = JobRequest.query.get_or_404(job_id)
    saved_items = json.loads(job.invoice_items) if job.invoice_items else []
    return render_template("admin/invoice_view.html", job=job, saved_items=saved_items)


@admin_bp.route("/invoices/<int:job_id>/pdf")
@admin_required
def invoice_pdf(job_id):
    from pdf_invoice import generate_invoice_pdf, invoice_number
    job = JobRequest.query.get_or_404(job_id)
    try:
        path = generate_invoice_pdf(job)
        return send_file(path, mimetype="application/pdf",
                         as_attachment=False,
                         download_name=f"MAS_Invoice_{invoice_number(job)}.pdf")
    except Exception as e:
        flash(f"Could not generate PDF: {str(e)}", "danger")
        return redirect(url_for("admin.invoice_view", job_id=job_id))


@admin_bp.route("/invoices/<int:job_id>/pdf/download")
@admin_required
def invoice_pdf_download(job_id):
    from pdf_invoice import generate_invoice_pdf, invoice_number
    job = JobRequest.query.get_or_404(job_id)
    path = generate_invoice_pdf(job)
    return send_file(path, mimetype="application/pdf",
                     as_attachment=True,
                     download_name=f"MAS_Invoice_{invoice_number(job)}.pdf")


@admin_bp.route("/invoices/<int:job_id>/send-whatsapp")
@admin_required
def invoice_send_whatsapp(job_id):
    from pdf_invoice import invoice_number
    from urllib.parse import quote
    job    = JobRequest.query.get_or_404(job_id)
    inv_no = invoice_number(job)
    pdf_url = url_for("admin.invoice_pdf_download", job_id=job_id, _external=True)

    lines = [
        "*MAS — Moussa for Aluminium Solutions*",
        "",
        f"Dear {job.client_name},",
        "",
        f"Please find your invoice *No. {inv_no}* for:",
        f"_{job.job_type}_ — {job.location}",
        "",
    ]
    if job.amount:
        lines.append(f"*Total: EGP {job.amount:,.2f}*")
        lines.append("")
    lines += ["Download your invoice PDF here:", pdf_url, "", "Thank you for your business."]

    message = "\n".join(lines)
    phone = "".join(c for c in (job.phone or "") if c.isdigit())
    if phone.startswith("0"):
        phone = "20" + phone[1:]
    elif not phone.startswith("20") and len(phone) == 10:
        phone = "20" + phone

    return redirect(f"https://wa.me/{phone}?text={quote(message)}")


@admin_bp.route("/invoices/<int:job_id>/send-email")
@admin_required
def invoice_send_email(job_id):
    from pdf_invoice import invoice_number
    from urllib.parse import quote
    job     = JobRequest.query.get_or_404(job_id)
    inv_no  = invoice_number(job)
    pdf_url = url_for("admin.invoice_pdf_download", job_id=job_id, _external=True)

    subject    = f"MAS Invoice {inv_no} — {job.job_type}"
    body_lines = [
        f"Dear {job.client_name},",
        "",
        f"Please find your invoice No. {inv_no} for:",
        f"  {job.job_type} — {job.location}",
        "",
    ]
    if job.amount:
        body_lines += [f"Total: EGP {job.amount:,.2f}", ""]
    body_lines += [
        "Download your invoice PDF:",
        pdf_url,
        "",
        "Thank you for your business.",
        "",
        "MAS — Moussa for Aluminium Solutions",
    ]

    body     = "\n".join(body_lines)
    to_email = job.phone if "@" in (job.phone or "") else ""

    return redirect(f"mailto:{to_email}?subject={quote(subject)}&body={quote(body)}")


@admin_bp.route("/invoices/<int:job_id>/save-amount", methods=["POST"])
@admin_required
def invoice_save_amount(job_id):
    job = JobRequest.query.get_or_404(job_id)
    data = request.get_json(silent=True) or {}
    amount_raw = data.get("amount", "")
    items = data.get("items", [])
    try:
        job.amount = float(amount_raw) if amount_raw else None
    except (ValueError, TypeError):
        return jsonify(ok=False, error="invalid_amount"), 400
    job.invoice_items = json.dumps(items)
    db.session.commit()
    return jsonify(ok=True, amount=job.amount)


@admin_bp.route("/invoices/<int:job_id>/mark", methods=["POST"])
@admin_required
def invoice_mark(job_id):
    job = JobRequest.query.get_or_404(job_id)
    job.invoiced = True
    db.session.commit()
    flash(f"Job #{job_id} marked as invoiced.", "success")
    return redirect(url_for("admin.invoices"))


@admin_bp.route("/invoices/<int:job_id>/delete", methods=["POST"])
@admin_required
def invoice_delete(job_id):
    job = JobRequest.query.get_or_404(job_id)
    job.invoiced = False
    job.amount = None
    job.invoice_items = None
    db.session.commit()
    flash(f"Invoice for Job #{job_id} ({job.client_name}) deleted.", "info")
    return redirect(url_for("admin.invoices") + "?tab=history")


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------
@admin_bp.route("/users")
@admin_required
def users_list():
    users = User.query.order_by(User.role, User.full_name).all()
    return render_template("admin/users_list.html", users=users)


@admin_bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_new():
    if request.method == "POST":
        err = _validate_user_form(request.form, editing=False)
        if err:
            flash(err, "danger")
            return render_template("admin/user_form.html", user=None), 400
        u = User(
            username  = request.form["username"].strip().lower(),
            full_name = request.form["full_name"].strip(),
            role      = request.form.get("role", ROLE_TECH),
        )
        u.set_password(request.form["password"])
        db.session.add(u)
        db.session.commit()
        flash(f"User '{u.username}' created.", "success")
        return redirect(url_for("admin.users_list"))
    return render_template("admin/user_form.html", user=None)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    u = User.query.get_or_404(user_id)
    if request.method == "POST":
        err = _validate_user_form(request.form, editing=True, current_user_id=user_id)
        if err:
            flash(err, "danger")
            return render_template("admin/user_form.html", user=u), 400
        u.full_name = request.form["full_name"].strip()
        u.role = request.form.get("role", ROLE_TECH)
        new_pw = request.form.get("password", "").strip()
        if new_pw:
            u.set_password(new_pw)
        db.session.commit()
        flash(f"User '{u.username}' updated.", "success")
        return redirect(url_for("admin.users_list"))
    return render_template("admin/user_form.html", user=u)


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@admin_required
def user_toggle(user_id):
    u = User.query.get_or_404(user_id)
    if u.id == current_user.id:
        flash("You cannot deactivate your own account.", "danger")
        return redirect(url_for("admin.users_list"))
    u.is_active_flag = not u.is_active_flag
    db.session.commit()
    state = "activated" if u.is_active_flag else "deactivated"
    flash(f"User '{u.username}' {state}.", "info")
    return redirect(url_for("admin.users_list"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _populate_job_from_form(job: JobRequest, form) -> JobRequest:
    client_id = form.get("client_id", type=int)
    job.client_id = client_id if client_id else None

    if client_id:
        client = Client.query.get(client_id)
        if client:
            job.client_name = client.name
            job.phone       = client.phone
            job.location    = (form.get("location") or client.location or "").strip() or "Other"
            job.address     = (form.get("address") or client.address or "").strip() or None
        else:
            job.client_id = None
            _fill_manual_client(job, form)
    else:
        _fill_manual_client(job, form)

    job.job_type    = (form.get("job_type")    or "").strip()
    job.description = (form.get("description") or "").strip() or None

    tech_id = form.get("technician_id", type=int)
    job.technician_id = tech_id if tech_id else None

    status = form.get("status") or STATUS_INCOMPLETE
    if status in (STATUS_VISIT, STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED):
        job.status = status
    if not hasattr(job, 'confirmed') or job.confirmed is None:
        job.confirmed = False

    expected = form.get("expected_date")
    if expected:
        try:
            job.expected_date = datetime.fromisoformat(expected)
        except ValueError:
            job.expected_date = None
    else:
        job.expected_date = None

    amount_raw = form.get("amount")
    job.amount = float(amount_raw) if amount_raw else None

    job.tech_notes = (form.get("tech_notes") or "").strip() or None

    if job.status == STATUS_COMPLETED and not job.completion_date:
        job.completion_date = datetime.utcnow()
    if job.status != STATUS_COMPLETED:
        job.completion_date = None

    return job


def _fill_manual_client(job: JobRequest, form) -> None:
    job.client_name = (form.get("client_name") or "").strip()
    job.phone       = (form.get("phone")        or "").strip()
    job.location    = (form.get("location")     or "").strip() or "Other"
    job.address     = (form.get("address")      or "").strip() or None


def _validate_user_form(form, editing=False, current_user_id=None):
    username  = (form.get("username")  or "").strip().lower()
    full_name = (form.get("full_name") or "").strip()
    password  = (form.get("password")  or "").strip()
    role      = form.get("role")

    if not full_name:
        return "Full name is required."
    if role not in (ROLE_ADMIN, ROLE_TECH):
        return "Invalid role."
    if not editing:
        if not username:
            return "Username is required."
        if not password or len(password) < 6:
            return "Password must be at least 6 characters."
        if User.query.filter_by(username=username).first():
            return f"Username '{username}' is already taken."
    else:
        if password and len(password) < 6:
            return "New password must be at least 6 characters."
    return None
