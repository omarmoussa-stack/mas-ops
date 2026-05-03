"""Authentication blueprint — login / logout."""
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user

from extensions import db
from models import User

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return _redirect_by_role(current_user)

    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or ""
        remember = bool(request.form.get("remember"))

        user = User.query.filter_by(username=username).first()
        if not user or not user.check_password(password) or not user.is_active_flag:
            flash("Invalid username or password.", "danger")
            return render_template("auth/login.html"), 401

        login_user(user, remember=remember)
        next_url = request.args.get("next")
        if next_url and next_url.startswith("/"):
            return redirect(next_url)
        return _redirect_by_role(user)

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


def _redirect_by_role(user: User):
    if user.is_admin:
        return redirect(url_for("admin.dashboard"))
    return redirect(url_for("tech.dashboard"))
