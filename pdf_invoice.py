"""PDF invoice generator for MAS Ops."""
import json
import os
from datetime import datetime

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

BASE_DIR    = os.path.abspath(os.path.dirname(__file__))
LOGO_PATH   = os.path.join(BASE_DIR, "static", "img", "mas_logo.png")
INVOICE_DIR = os.path.join(BASE_DIR, "instance", "invoices")
os.makedirs(INVOICE_DIR, exist_ok=True)

GRAY_DARK  = HexColor("#1a1a1a")
GRAY_MID   = HexColor("#4a4a4a")
GRAY_MUTED = HexColor("#6b6b6b")
GRAY_LIGHT = HexColor("#e0e0e0")
GRAY_FAINT = HexColor("#f0f0f0")
ACCENT     = HexColor("#2c2c2c")


def invoice_number(job) -> str:
    year = (job.completion_date or job.created_at or datetime.utcnow()).year
    return f"{year}-{job.id:04d}"


def generate_invoice_pdf(job) -> str:
    items    = json.loads(job.invoice_items) if job.invoice_items else []
    inv_no   = invoice_number(job)
    inv_date = (job.completion_date or job.created_at or datetime.utcnow()).strftime("%d %b %Y")

    filepath = os.path.join(INVOICE_DIR, f"MAS_Invoice_{inv_no}.pdf")

    c = canvas.Canvas(filepath, pagesize=A4)
    page_w, page_h = A4
    margin  = 20 * mm
    x_left  = margin
    x_right = page_w - margin
    y       = page_h - margin

    # ── Header: logo + INVOICE label ──────────────────────────────────────
    if os.path.exists(LOGO_PATH):
        try:
            logo   = ImageReader(LOGO_PATH)
            logo_h = 35 * mm
            logo_w = logo_h * 2.5
            c.drawImage(logo, x_left, y - logo_h, width=logo_w, height=logo_h,
                        preserveAspectRatio=True, mask="auto")
        except Exception:
            _draw_text_logo(c, x_left, y)
    else:
        _draw_text_logo(c, x_left, y)

    c.setFont("Helvetica-Bold", 22)
    c.setFillColor(GRAY_DARK)
    c.drawRightString(x_right, y - 4 * mm, "INVOICE")
    c.setFont("Helvetica", 10)
    c.setFillColor(GRAY_MUTED)
    c.drawRightString(x_right, y - 11 * mm, f"No. {inv_no}")
    c.drawRightString(x_right, y - 17 * mm, f"Date: {inv_date}")

    y -= 30 * mm

    # ── Divider ───────────────────────────────────────────────────────────
    c.setStrokeColor(GRAY_LIGHT)
    c.setLineWidth(0.5)
    c.line(x_left, y, x_right, y)
    y -= 8 * mm

    # ── Bill-to + Job details (two columns) ───────────────────────────────
    col_r = page_w / 2 + 5 * mm

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(GRAY_MUTED)
    c.drawString(x_left, y, "BILL TO")
    c.drawString(col_r, y, "JOB DETAILS")
    y -= 6 * mm

    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(GRAY_DARK)
    c.drawString(x_left, y, job.client_name or "—")

    _kv(c, col_r, y, "Type:", job.job_type or "—", 12 * mm)
    y -= 5 * mm

    c.setFont("Helvetica", 9)
    c.setFillColor(GRAY_MID)
    c.drawString(x_left, y, job.phone or "")

    tech = job.technician.full_name if job.technician else "—"
    _kv(c, col_r, y, "Technician:", tech, 20 * mm)
    y -= 5 * mm

    location_line = job.location or ""
    if job.address:
        location_line = f"{job.address}, {location_line}" if location_line else job.address
    c.setFont("Helvetica", 9)
    c.setFillColor(GRAY_MID)
    c.drawString(x_left, y, location_line)

    _kv(c, col_r, y, "Job ref:", f"#{job.id}", 14 * mm)
    y -= 14 * mm

    # ── Line-items table ──────────────────────────────────────────────────
    col_desc_w  = 95 * mm
    col_qty_w   = 18 * mm
    col_price_w = 27 * mm
    col_total_w = 30 * mm

    col_qty_x   = x_left + col_desc_w
    col_price_x = col_qty_x + col_qty_w
    col_total_x = col_price_x + col_price_w
    table_r     = col_total_x + col_total_w

    c.setFont("Helvetica-Bold", 8)
    c.setFillColor(GRAY_MUTED)
    c.drawString(x_left + 2, y, "DESCRIPTION")
    c.drawRightString(col_qty_x   + col_qty_w   - 2, y, "QTY")
    c.drawRightString(col_price_x + col_price_w - 2, y, "UNIT PRICE")
    c.drawRightString(table_r     - 2,            y, "TOTAL")
    y -= 3 * mm

    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.2)
    c.line(x_left, y, table_r, y)
    y -= 6 * mm

    if items:
        for item in items:
            desc       = str(item.get("desc", ""))
            qty        = float(item.get("qty", 1))
            price      = float(item.get("price", 0))
            line_total = qty * price

            c.setFont("Helvetica", 10)
            c.setFillColor(GRAY_DARK)
            c.drawString(x_left + 2, y, desc[:60])
            c.drawRightString(col_qty_x   + col_qty_w   - 2, y, f"{qty:g}")
            c.drawRightString(col_price_x + col_price_w - 2, y, f"EGP {price:,.0f}")
            c.drawRightString(table_r     - 2,            y, f"EGP {line_total:,.0f}")

            y -= 4 * mm
            c.setStrokeColor(GRAY_FAINT)
            c.setLineWidth(0.3)
            c.line(x_left, y, table_r, y)
            y -= 5 * mm
    else:
        amt = float(job.amount or 0)
        c.setFont("Helvetica", 10)
        c.setFillColor(GRAY_DARK)
        c.drawString(x_left + 2, y, job.job_type or "Service")
        c.drawRightString(col_qty_x   + col_qty_w   - 2, y, "1")
        c.drawRightString(col_price_x + col_price_w - 2, y, f"EGP {amt:,.0f}")
        c.drawRightString(table_r     - 2,            y, f"EGP {amt:,.0f}")
        y -= 9 * mm

    # ── Totals block ──────────────────────────────────────────────────────
    y -= 4 * mm
    total = float(job.amount or 0)

    c.setFont("Helvetica", 10)
    c.setFillColor(GRAY_MUTED)
    c.drawRightString(col_total_x - 4, y, "Subtotal")
    c.setFillColor(GRAY_DARK)
    c.drawRightString(table_r - 2, y, f"EGP {total:,.0f}")
    y -= 7 * mm

    c.setStrokeColor(ACCENT)
    c.setLineWidth(1.2)
    c.line(col_price_x, y + 3 * mm, table_r, y + 3 * mm)

    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(GRAY_DARK)
    c.drawRightString(col_total_x - 4, y - 2 * mm, "Total")
    c.drawRightString(table_r - 2,     y - 2 * mm, f"EGP {total:,.2f}")

    # ── Footer ────────────────────────────────────────────────────────────
    footer_y = 18 * mm
    c.setStrokeColor(GRAY_LIGHT)
    c.setLineWidth(0.5)
    c.line(x_left, footer_y + 6 * mm, x_right, footer_y + 6 * mm)
    c.setFont("Helvetica", 8)
    c.setFillColor(GRAY_MUTED)
    c.drawString(x_left,  footer_y, "MAS — Moussa for Aluminium Solutions")
    c.drawRightString(x_right, footer_y, "Thank you for your business")

    c.showPage()
    c.save()
    return filepath


def _draw_text_logo(c, x, y):
    c.setFont("Helvetica-Bold", 26)
    c.setFillColor(GRAY_DARK)
    c.drawString(x, y - 8 * mm, "MAS")
    c.setFont("Helvetica", 8)
    c.setFillColor(GRAY_MUTED)
    c.drawString(x, y - 14 * mm, "MOUSSA FOR ALUMINIUM SOLUTIONS")


def _kv(c, x, y, label, value, label_w):
    c.setFont("Helvetica-Bold", 9)
    c.setFillColor(GRAY_DARK)
    c.drawString(x, y, label)
    c.setFont("Helvetica", 9)
    c.setFillColor(GRAY_MID)
    c.drawString(x + label_w, y, value)
