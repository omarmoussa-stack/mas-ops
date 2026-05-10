"""MAS Ops — Flask application factory."""
from datetime import datetime
from functools import wraps

from flask import Flask, jsonify, request, redirect, url_for, abort
from flask_login import current_user, login_required

from config import DevelopmentConfig
from extensions import db, login_manager
from models import (
    JobRequest, User,
    ROLE_ADMIN,
    STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED,
)


def admin_required(view_fn):
    @wraps(view_fn)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != ROLE_ADMIN:
            abort(403)
        return view_fn(*args, **kwargs)
    return wrapper


def _migrate(db):
    """Idempotent ALTER TABLE statements — safe to run on every reload."""
    from sqlalchemy import text
    migrations = [
        "ALTER TABLE job_requests ADD COLUMN is_archived BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE job_requests ADD COLUMN confirmed BOOLEAN NOT NULL DEFAULT 0",
        "ALTER TABLE job_requests ADD COLUMN payment_received FLOAT DEFAULT 0",
        "ALTER TABLE job_requests ADD COLUMN client_id INTEGER REFERENCES clients(id)",
        "DELETE FROM notifications WHERE link LIKE '/admin/%' OR link LIKE '/tech/%' OR link LIKE '/clients/%'",
    ]
    for sql in migrations:
        try:
            db.session.execute(text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


def create_app(config_object=DevelopmentConfig):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object)

    db.init_app(app)
    login_manager.init_app(app)

    from extensions import csrf
    csrf.init_app(app)

    # ── Blueprints ──────────────────────────────────────────────────────
    from blueprints.auth          import auth_bp
    from admin                    import admin_bp
    from blueprints.tech          import tech_bp
    from blueprints.notifications import notif_bp
    from blueprints.clients       import clients_bp
    from blueprints.appointments  import appointments_bp

    app.register_blueprint(auth_bp,     url_prefix="/auth")
    app.register_blueprint(admin_bp,    url_prefix="/admin")
    app.register_blueprint(tech_bp,     url_prefix="/tech")
    app.register_blueprint(notif_bp,    url_prefix="/notifications")
    app.register_blueprint(clients_bp,  url_prefix="/clients")
    app.register_blueprint(appointments_bp, url_prefix="/appointments")

    # Exempt JSON-only blueprints from CSRF (they use token auth or fetch APIs)
    csrf.exempt(notif_bp)
    csrf.exempt(tech_bp)

    # ── Inject config into all templates (for JOB_LOCATIONS etc.) ──────
    from config import Config
    @app.context_processor
    def inject_config():
        return {"config": Config}

    with app.app_context():
        db.create_all()

    # ── Routes ──────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login"))
        if current_user.is_admin:
            return redirect(url_for("admin.dashboard"))
        return redirect(url_for("tech.dashboard"))

    # Calendar JSON feed
    @app.route("/api/calendar/events")
    @admin_required
    def calendar_events():
        start_param   = request.args.get("start")
        end_param     = request.args.get("end")
        tech_id       = request.args.get("technician_id", type=int)
        status_filter = request.args.get("status")
        upcoming_only = request.args.get("upcoming", "1") == "1"

        query = JobRequest.query.filter(
            JobRequest.expected_date.isnot(None),
            JobRequest.is_archived == False,
        )

        # Hide past jobs by default - only show today and upcoming
        if upcoming_only:
            from datetime import timedelta
            today_start = datetime.combine(datetime.utcnow().date(), datetime.min.time()) - timedelta(hours=3)
            query = query.filter(JobRequest.expected_date >= today_start)

        if start_param:
            try:
                query = query.filter(
                    JobRequest.expected_date >= datetime.fromisoformat(
                        start_param.replace("Z", "+00:00")
                    )
                )
            except ValueError:
                pass
        if end_param:
            try:
                query = query.filter(
                    JobRequest.expected_date <= datetime.fromisoformat(
                        end_param.replace("Z", "+00:00")
                    )
                )
            except ValueError:
                pass
        if tech_id:
            query = query.filter(JobRequest.technician_id == tech_id)
        if status_filter in (STATUS_INCOMPLETE, STATUS_IN_PROCESS, STATUS_COMPLETED):
            query = query.filter(JobRequest.status == status_filter)

        jobs = query.order_by(JobRequest.expected_date.asc()).all()
        return jsonify([job.to_calendar_event(include_amount=True) for job in jobs])

    # Ledger-pro sync
    @app.route("/api/internal/sync-project", methods=["POST"])
    def internal_sync_project():
        token    = request.headers.get("X-Sync-Token", "")
        expected = app.config.get("INTERNAL_SYNC_TOKEN", "mas-ledger-sync-2026")
        if token != expected:
            return jsonify(ok=False, error="unauthorized"), 401

        data = request.get_json(silent=True) or {}

        expected_date = None
        start_str = (data.get("start_date") or "").strip()
        if start_str:
            try:
                expected_date = datetime.fromisoformat(start_str)
            except ValueError:
                pass

        quote = data.get("total_quote")
        email = (data.get("client_email") or "").strip()
        desc_parts = ["Synced from Project Ledger"]
        if quote:
            desc_parts.append(f"Quote: EGP {float(quote):.2f}")
        if email:
            desc_parts.append(f"Email: {email}")

        job = JobRequest(
            client_name   = (data.get("client_name") or "").strip() or "Unknown",
            phone         = email,
            location      = (data.get("project_location") or "").strip() or "Other",
            job_type      = (data.get("type") or "").strip() or "Other",
            description   = " | ".join(desc_parts),
            amount        = float(quote) if quote else None,
            expected_date = expected_date,
            status        = STATUS_INCOMPLETE,
        )
        db.session.add(job)

        from models import notify_admins, NOTIF_INFO
        notify_admins(
            f"📋 New project synced from Ledger: {job.client_name} — {job.job_type}",
            link=url_for("admin.jobs_list"),
            type=NOTIF_INFO,
        )
        db.session.commit()
        return jsonify(ok=True, job_id=job.id)

    csrf.exempt(internal_sync_project)

    # ── CLI helpers ──────────────────────────────────────────────────────
    @app.cli.command("seed-admin")
    def seed_admin():
        if User.query.filter_by(role=ROLE_ADMIN).first():
            print("Admin already exists — skipping.")
            return
        admin = User(username="admin", full_name="MAS Administrator", role=ROLE_ADMIN)
        admin.set_password("changeme")
        db.session.add(admin)
        db.session.commit()
        print("Created admin / password: changeme  (CHANGE IT IMMEDIATELY)")

    @app.cli.command("create-tech")
    def create_tech():
        from models import ROLE_TECH
        if User.query.filter_by(username="tech1").first():
            print("Tech 'tech1' already exists — skipping.")
            return
        tech = User(username="tech1", full_name="Technician One", role=ROLE_TECH)
        tech.set_password("tech123")
        db.session.add(tech)
        db.session.commit()
        print("Created tech1 / password: tech123")

    # ── Error handlers ───────────────────────────────────────────────────
    @app.errorhandler(403)
    def forbidden(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="forbidden"), 403
        return "403 — Forbidden", 403

    @app.errorhandler(404)
    def not_found(_e):
        if request.path.startswith("/api/"):
            return jsonify(error="not_found"), 404
        return "404 — Not Found", 404

    @app.route("/sw.js")
    def service_worker():
        from flask import send_from_directory, current_app
        response = send_from_directory(
            current_app.static_folder,
            "sw.js",
            mimetype="application/javascript",
        )
        response.headers["Service-Worker-Allowed"] = "/"
        response.headers["Cache-Control"] = "no-cache"
        return response

    return app


app = create_app()

with app.app_context():
    from extensions import db as _db
    _migrate(_db)

# ── URL prefix middleware ─────────────────────────────────────────────────────
# When URL_PREFIX=/masops is set (production), the app mounts at that path.
# When unset (local dev), it serves from root as before.
import os as _os
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.exceptions import NotFound as _NotFound

_URL_PREFIX = _os.environ.get("URL_PREFIX", "").rstrip("/")

if _URL_PREFIX:
    app.config["APPLICATION_ROOT"] = _URL_PREFIX
    application = DispatcherMiddleware(_NotFound(), {_URL_PREFIX: app})
else:
    application = app

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=True)
