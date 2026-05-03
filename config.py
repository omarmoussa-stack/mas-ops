"""Application configuration.

Keep secrets out of version control. On PythonAnywhere, set environment
variables in the WSGI file or a .env loaded at startup.
"""
import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "change-me-in-production")

    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "MASOPS_DATABASE_URL",
        os.environ.get(
            "DATABASE_URL",
            f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'mas.db')}",
        ),
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"

    INTERNAL_SYNC_TOKEN = os.environ.get("INTERNAL_SYNC_TOKEN", "mas-ledger-sync-2026")

    JOB_LOCATIONS = ["East Cairo", "West Cairo", "North Coast", "New Capital", "Other"]
    JOB_TYPES = [
        "Shutter Maintenance",
        "Shutter Installation",
        "Aluminum Installation",
        "Aluminum Repair",
        "Inspection",
        "Other",
    ]


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True


class DevelopmentConfig(Config):
    DEBUG = True
