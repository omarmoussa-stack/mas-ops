"""Clients blueprint — registry of repeat customers.

Routes
------
GET  /clients/                  list with search
GET  /clients/new               create form
POST /clients/new               save new client
GET  /clients/<id>              profile page (job history + stats)
GET  /clients/<id>/edit         edit form
POST /clients/<id>/edit         save edits
GET  /clients/api/search?q=     JSON autocomplete (used by job form)
"""
from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, abort, jsonify,
)
from flask_login import current_user, login_required

from extensions import db
from models import Client, JobRequest, STATUS_COMPLETED

clients_bp = Blueprint("clients", __name__, template_folder="../templates/clients")


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
@clients_bp.route("/")
@admin_required
def clients_list():
    q = request.args.get("q", "").strip()
    location = request.args.get("location", "").strip()
    query = Client.query
    if q:
        query = query.filter(
            db.or_(
                Client.name.ilike(f"%{q}%"),
                Client.phone.ilike(f"%{q}%"),
            )
        )
    if location:
        query = query.filter(Client.location == location)
    clients = query.order_by(Client.name.asc()).all()

    locations = [
        r.location for r in
        db.session.query(Client.location).distinct().filter(Client.location.isnot(None)).all()
    ]
    return render_template(
        "clients/list.html",
        clients=clients,
        q=q,
        location_filter=location,
        locations=sorted(locations),
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------
@clients_bp.route("/new", methods=["GET", "POST"])
@admin_required
def client_new():
    if request.method == "POST":
        err = _validate_client_form(request.form)
        if err:
            flash(err, "danger")
            return render_template("clients/form.html", client=None), 400
        c = Client(
            name     = request.form["name"].strip(),
            phone    = request.form["phone"].strip(),
            location = request.form.get("location", "").strip() or None,
            address  = request.form.get("address", "").strip() or None,
            notes    = request.form.get("notes", "").strip() or None,
        )
        db.session.add(c)
        db.session.commit()
        flash(f"Client '{c.name}' added.", "success")
        return redirect(url_for("clients.client_profile", client_id=c.id))
    return render_template("clients/form.html", client=None)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
@clients_bp.route("/<int:client_id>")
@admin_required
def client_profile(client_id):
    client = Client.query.get_or_404(client_id)
    jobs = client.jobs.order_by(JobRequest.created_at.desc()).all()
    other_clients = []
    if client.location:
        other_clients = (
            Client.query
            .filter(Client.location == client.location, Client.id != client.id)
            .limit(5).all()
        )
    return render_template("clients/profile.html", client=client, jobs=jobs, other_clients=other_clients)


# ---------------------------------------------------------------------------
# Edit
# ---------------------------------------------------------------------------
@clients_bp.route("/<int:client_id>/edit", methods=["GET", "POST"])
@admin_required
def client_edit(client_id):
    client = Client.query.get_or_404(client_id)
    if request.method == "POST":
        err = _validate_client_form(request.form)
        if err:
            flash(err, "danger")
            return render_template("clients/form.html", client=client), 400
        client.name     = request.form["name"].strip()
        client.phone    = request.form["phone"].strip()
        client.location = request.form.get("location", "").strip() or None
        client.address  = request.form.get("address", "").strip() or None
        client.notes    = request.form.get("notes", "").strip() or None
        db.session.commit()
        flash(f"Client '{client.name}' updated.", "success")
        return redirect(url_for("clients.client_profile", client_id=client.id))
    return render_template("clients/form.html", client=client)


# ---------------------------------------------------------------------------
# JSON search — used by the job-form autocomplete widget
# ---------------------------------------------------------------------------
@clients_bp.route("/api/search")
@admin_required
def api_search():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    results = (
        Client.query
        .filter(
            db.or_(
                Client.name.ilike(f"%{q}%"),
                Client.phone.ilike(f"%{q}%"),
            )
        )
        .order_by(Client.name.asc())
        .limit(10)
        .all()
    )
    return jsonify([c.to_search_dict() for c in results])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------
def _validate_client_form(form) -> Optional[str]:
    name  = (form.get("name")  or "").strip()
    phone = (form.get("phone") or "").strip()
    if not name:
        return "Client name is required."
    if not phone:
        return "Phone number is required."
    return None
