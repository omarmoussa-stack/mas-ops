#!/usr/bin/env python3
"""
MAS Ops — Visit Reminder Script
================================
Run by PythonAnywhere scheduled tasks every hour.
Sends email reminders at:
  - 3:00 PM day before  (15:00)
  - 8:00 PM day before  (20:00)
  - 8:00 AM same day    (08:00)

Setup on PythonAnywhere:
  Tasks -> Add task -> hourly
  Command: python3 /home/omarmoussa/mas-ops/scripts/remind.py
"""

import os
import sys
import smtplib
from datetime import datetime, timedelta, date
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ── Path setup ────────────────────────────────────────────────────────────────
sys.path.insert(0, "/home/omarmoussa/mas-ops")
os.environ.setdefault("MASOPS_DATABASE_URL", "sqlite:////home/omarmoussa/mas-ops/instance/mas.db")
os.environ.setdefault("SECRET_KEY", "remind-script-key")

# ── Config ────────────────────────────────────────────────────────────────────
MAIL_HOST     = os.environ.get("MAIL_SERVER",   "smtp.gmail.com")
MAIL_PORT     = int(os.environ.get("MAIL_PORT", 587))
MAIL_USER     = os.environ.get("MAIL_USERNAME", "")
MAIL_PASS     = os.environ.get("MAIL_PASSWORD", "")
REMIND_TO     = os.environ.get("REMIND_EMAIL",  MAIL_USER)  # send to yourself

# Reminder windows: (hour_to_trigger, label, days_ahead)
REMINDER_SLOTS = [
    (15, "🔔 Tomorrow's Visits",  1),   # 3PM day before
    (20, "⏰ Reminder: Visits Tomorrow", 1),   # 8PM day before
    (8,  "🚨 Today's Visits",     0),   # 8AM same day
]

def get_visits_for_date(target_date):
    """Query visits (STATUS_VISIT or any status) scheduled for target_date."""
    from app import app
    from models import JobRequest, STATUS_VISIT, STATUS_INCOMPLETE, STATUS_IN_PROCESS

    with app.app_context():
        start = datetime.combine(target_date, datetime.min.time())
        end   = datetime.combine(target_date, datetime.max.time())
        jobs  = (
            JobRequest.query
            .filter(
                JobRequest.is_archived == False,
                JobRequest.expected_date >= start,
                JobRequest.expected_date <= end,
                JobRequest.status.in_([STATUS_VISIT, STATUS_INCOMPLETE, STATUS_IN_PROCESS])
            )
            .order_by(JobRequest.expected_date.asc())
            .all()
        )
        return [
            {
                "id":         j.id,
                "client":     j.client_name,
                "phone":      j.phone,
                "type":       j.job_type,
                "location":   j.location,
                "time":       j.expected_date.strftime("%I:%M %p") if j.expected_date else "TBD",
                "status":     j.status,
                "technician": j.technician.full_name if j.technician else "Unassigned",
                "confirmed":  getattr(j, "confirmed", False),
            }
            for j in jobs
        ]

def build_email(subject, visits, target_date):
    """Build plain-text + HTML email."""
    date_label = target_date.strftime("%A, %d %B %Y")

    # Plain text
    lines = [f"MAS Ops — {subject}", f"Date: {date_label}", "=" * 40, ""]
    for v in visits:
        confirmed = "✅ Confirmed" if v["confirmed"] else "⏳ Awaiting"
        lines.append(f"  #{v['id']} — {v['time']}  {v['client']}")
        lines.append(f"       {v['type']} | {v['location']}")
        lines.append(f"       Tech: {v['technician']}  |  {confirmed}")
        lines.append("")
    lines.append(f"Total: {len(visits)} visit(s)")
    lines.append("")
    lines.append("— MAS Ops System")
    plain = "\n".join(lines)

    # HTML
    rows = ""
    for v in visits:
        confirmed_badge = (
            '<span style="color:#16a34a;font-weight:bold">✅ Confirmed</span>'
            if v["confirmed"] else
            '<span style="color:#d97706;font-weight:bold">⏳ Awaiting</span>'
        )
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333;color:#a78bfa">#{v['id']}</td>
          <td style="padding:8px;border-bottom:1px solid #333;font-weight:bold">{v['client']}<br>
              <span style="color:#888;font-size:12px">{v['phone']}</span></td>
          <td style="padding:8px;border-bottom:1px solid #333">{v['type']}</td>
          <td style="padding:8px;border-bottom:1px solid #333">{v['location']}</td>
          <td style="padding:8px;border-bottom:1px solid #333">{v['time']}</td>
          <td style="padding:8px;border-bottom:1px solid #333">{v['technician']}</td>
          <td style="padding:8px;border-bottom:1px solid #333">{confirmed_badge}</td>
        </tr>"""

    html = f"""
    <div style="font-family:Arial,sans-serif;background:#1a1a2e;color:#e2e8f0;padding:24px;border-radius:12px;max-width:700px">
      <div style="display:flex;align-items:center;margin-bottom:20px">
        <span style="font-size:24px;font-weight:bold;color:#a78bfa">✕ MAS Ops</span>
        <span style="margin-left:12px;color:#888">Visit Reminder</span>
      </div>
      <h2 style="color:#a78bfa;margin-bottom:4px">{subject}</h2>
      <p style="color:#888;margin-top:0">{date_label}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px">
        <thead>
          <tr style="background:#2d1f42">
            <th style="padding:10px;text-align:left;color:#a78bfa">#</th>
            <th style="padding:10px;text-align:left;color:#a78bfa">Client</th>
            <th style="padding:10px;text-align:left;color:#a78bfa">Type</th>
            <th style="padding:10px;text-align:left;color:#a78bfa">Location</th>
            <th style="padding:10px;text-align:left;color:#a78bfa">Time</th>
            <th style="padding:10px;text-align:left;color:#a78bfa">Technician</th>
            <th style="padding:10px;text-align:left;color:#a78bfa">Status</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:20px;color:#888;font-size:13px">
        Total: <strong style="color:#e2e8f0">{len(visits)} visit(s)</strong> scheduled for {date_label}
      </p>
      <p style="color:#555;font-size:12px;margin-top:24px">— MAS Ops Automated Reminder</p>
    </div>"""

    return plain, html

def send_email(subject, plain, html):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"MAS Ops — {subject}"
    msg["From"]    = f"MAS Ops <{MAIL_USER}>"
    msg["To"]      = REMIND_TO

    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(html,  "html"))

    with smtplib.SMTP(MAIL_HOST, MAIL_PORT) as server:
        server.starttls()
        server.login(MAIL_USER, MAIL_PASS)
        server.sendmail(MAIL_USER, REMIND_TO, msg.as_string())

def main():
    now        = datetime.now()
    current_hr = now.hour

    for trigger_hour, subject, days_ahead in REMINDER_SLOTS:
        if current_hr != trigger_hour:
            continue

        target_date = (now + timedelta(days=days_ahead)).date()
        visits      = get_visits_for_date(target_date)

        if not visits:
            print(f"[{now.strftime('%H:%M')}] No visits on {target_date} — skipping.")
            continue

        plain, html = build_email(subject, visits, target_date)
        send_email(subject, plain, html)
        print(f"[{now.strftime('%H:%M')}] ✅ Sent '{subject}' — {len(visits)} visit(s) on {target_date}")
        return  # only one reminder per run

    print(f"[{now.strftime('%H:%M')}] Not a reminder hour — nothing to send.")

if __name__ == "__main__":
    main()
