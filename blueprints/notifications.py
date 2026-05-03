"""Notifications blueprint — JSON API for the navbar bell widget."""
from flask import Blueprint, jsonify, abort
from flask_login import login_required, current_user

from extensions import db
from models import Notification

notif_bp = Blueprint("notifications", __name__)


@notif_bp.route("/feed")
@login_required
def feed():
    recent = (
        Notification.query
        .filter_by(user_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .limit(15)
        .all()
    )
    unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify(unread=unread, notifications=[n.to_dict() for n in recent])


@notif_bp.route("/<int:notif_id>/read", methods=["POST"])
@login_required
def mark_read(notif_id):
    n = Notification.query.get_or_404(notif_id)
    if n.user_id != current_user.id:
        abort(403)
    n.is_read = True
    db.session.commit()
    return jsonify(ok=True)


@notif_bp.route("/read-all", methods=["POST"])
@login_required
def read_all():
    Notification.query.filter_by(user_id=current_user.id, is_read=False).update({"is_read": True})
    db.session.commit()
    return jsonify(ok=True)
