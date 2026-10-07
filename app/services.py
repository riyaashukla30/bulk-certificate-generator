import logging
from collections import Counter
from datetime import date
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfgen import canvas

from app.models import (
    CERT_FAILED,
    CERT_PENDING,
    CERT_SUCCESS,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PARTIAL,
    JOB_PROCESSING,
    Certificate,
    Job,
)

logger = logging.getLogger(__name__)


def generate_certificate_pdf(path: Path, name: str, event_name: str,
                             issued_by: str, issue_date: date, achievement: str | None) -> None:
    """Ek hi predefined template: landscape A4, border, centered text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = landscape(A4)
    c = canvas.Canvas(str(path), pagesize=(width, height))

    # double border
    c.setStrokeColor(HexColor("#1F3A5F"))
    c.setLineWidth(4)
    c.rect(25, 25, width - 50, height - 50)
    c.setLineWidth(1)
    c.rect(35, 35, width - 70, height - 70)

    c.setFillColor(HexColor("#1F3A5F"))
    c.setFont("Helvetica-Bold", 38)
    c.drawCentredString(width / 2, height - 120, "CERTIFICATE")
    c.setFont("Helvetica", 16)
    c.drawCentredString(width / 2, height - 150, "OF ACHIEVEMENT")

    c.setFillColor(HexColor("#333333"))
    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 210, "This is proudly presented to")

    c.setFillColor(HexColor("#B8860B"))
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(width / 2, height - 265, name)
    c.line(width / 2 - 200, height - 275, width / 2 + 200, height - 275)

    c.setFillColor(HexColor("#333333"))
    c.setFont("Helvetica", 14)
    c.drawCentredString(width / 2, height - 315, achievement or "for successful participation in")
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2, height - 350, event_name)

    c.setFont("Helvetica", 12)
    c.drawString(80, 80, f"Date: {issue_date.strftime('%d %B %Y')}")
    c.drawRightString(width - 80, 80, f"Issued by: {issued_by}")
    c.save()


def status_counts(db, job_id: str) -> dict:
    statuses = db.query(Certificate.status).filter(Certificate.job_id == job_id).all()
    counts = Counter(s for (s,) in statuses)
    return {
        "total": sum(counts.values()),
        "succeeded": counts[CERT_SUCCESS],
        "failed": counts[CERT_FAILED],
        "pending": counts[CERT_PENDING],
    }


def refresh_job_status(db, job: Job) -> None:
    """Certificates ke status se job ka final status nikalta hai."""
    counts = status_counts(db, job.id)
    if counts["pending"] > 0:
        job.status = JOB_PROCESSING
    elif counts["failed"] == 0:
        job.status = JOB_COMPLETED
    elif counts["succeeded"] == 0:
        job.status = JOB_FAILED
    else:
        job.status = JOB_PARTIAL
    db.commit()


def process_job(session_factory, job_id: str, output_dir: Path) -> None:
    """Background mein chalta hai. Apna alag DB session use karta hai."""
    db = session_factory()
    try:
        job = db.get(Job, job_id)
        job.status = JOB_PROCESSING
        db.commit()

        pending = db.query(Certificate).filter_by(job_id=job_id, status=CERT_PENDING).all()
        for cert in pending:
            try:
                path = Path(output_dir) / job_id / f"{cert.id}.pdf"
                generate_certificate_pdf(path, cert.recipient_name, job.event_name,
                                         job.issued_by, job.issue_date, cert.achievement)
                cert.status = CERT_SUCCESS
                cert.file_path = str(path)
            except Exception as exc:  # ek fail hone se baaki nahi rukne chahiye
                logger.exception("Certificate %s failed", cert.id)
                cert.status = CERT_FAILED
                cert.error = f"Generation failed: {exc}"
            db.commit()  # har certificate ke baad commit -> live progress

        refresh_job_status(db, job)
    except Exception:
        logger.exception("Job %s crashed", job_id)
        db.rollback()
        job = db.get(Job, job_id)
        job.status = JOB_FAILED
        db.commit()
    finally:
        db.close()
