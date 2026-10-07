import io
import os
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.database import make_session_factory
from app.models import (CERT_FAILED, CERT_PENDING, CERT_SUCCESS, JOB_COMPLETED, JOB_FAILED,
                        JOB_PARTIAL, Certificate, Job)
from app.schemas import JobCreate, validate_recipient
from app.services import process_job, refresh_job_status, status_counts


def create_app(db_url: Optional[str] = None, output_dir: Optional[str] = None) -> FastAPI:
    db_url = db_url or os.getenv("DATABASE_URL", "sqlite:///./certificates.db")
    output_dir = Path(output_dir or os.getenv("OUTPUT_DIR", "generated"))
    output_dir.mkdir(parents=True, exist_ok=True)
    SessionLocal = make_session_factory(db_url)

    app = FastAPI(title="Bulk Certificate Generator")

    def get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def get_job_or_404(db: Session, job_id: str) -> Job:
        job = db.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return job

    def job_summary(db: Session, job: Job) -> dict:
        return {
            "job_id": job.id,
            "status": job.status,
            "event_name": job.event_name,
            "created_at": job.created_at,
            **status_counts(db, job.id),
            "certificates_url": f"/jobs/{job.id}/certificates",
            "download_all_url": f"/jobs/{job.id}/download",
        }

    @app.post("/jobs", status_code=202)
    def create_job(req: JobCreate, background: BackgroundTasks, db: Session = Depends(get_db)):
        job = Job(event_name=req.event_name, issued_by=req.issued_by, issue_date=req.issue_date)
        db.add(job)
        db.flush()  # job.id mil jaye

        for raw in req.recipients:
            recipient, error = validate_recipient(raw)
            if error:
                # galat recipient: job reject nahi, bas is certificate ko failed mark karo
                name = raw.get("name") if isinstance(raw.get("name"), str) else None
                email = raw.get("email") if isinstance(raw.get("email"), str) else None
                db.add(Certificate(job_id=job.id, recipient_name=name, recipient_email=email,
                                   status=CERT_FAILED, error=f"Validation error: {error}"))
            else:
                db.add(Certificate(job_id=job.id, recipient_name=recipient.name,
                                   recipient_email=recipient.email,
                                   achievement=recipient.achievement, status=CERT_PENDING))
        db.commit()

        if status_counts(db, job.id)["pending"] > 0:
            background.add_task(process_job, SessionLocal, job.id, output_dir)
        else:
            refresh_job_status(db, job)  # sab invalid the, koi kaam hi nahi
        return job_summary(db, job)

    @app.get("/jobs/{job_id}")
    def get_job(job_id: str, db: Session = Depends(get_db)):
        return job_summary(db, get_job_or_404(db, job_id))

    @app.get("/jobs/{job_id}/certificates")
    def list_certificates(job_id: str,
                          status: Optional[str] = Query(None, pattern="^(pending|success|failed)$"),
                          limit: int = Query(100, ge=1, le=500),
                          offset: int = Query(0, ge=0),
                          db: Session = Depends(get_db)):
        get_job_or_404(db, job_id)
        q = db.query(Certificate).filter(Certificate.job_id == job_id)
        if status:
            q = q.filter(Certificate.status == status)
        total = q.count()
        items = q.order_by(Certificate.id).offset(offset).limit(limit).all()
        return {
            "total": total, "limit": limit, "offset": offset,
            "items": [{
                "certificate_id": c.id,
                "recipient_name": c.recipient_name,
                "recipient_email": c.recipient_email,
                "status": c.status,
                "error": c.error,
                "download_url": f"/certificates/{c.id}/download" if c.status == CERT_SUCCESS else None,
            } for c in items],
        }

    @app.get("/certificates/{certificate_id}/download")
    def download_certificate(certificate_id: str, db: Session = Depends(get_db)):
        cert = db.get(Certificate, certificate_id)
        if not cert:
            raise HTTPException(404, "Certificate not found")
        if cert.status != CERT_SUCCESS or not cert.file_path or not Path(cert.file_path).exists():
            raise HTTPException(409, f"Certificate is not available (status: {cert.status})")
        return FileResponse(cert.file_path, media_type="application/pdf",
                            filename=f"certificate_{cert.id}.pdf")

    @app.get("/jobs/{job_id}/download")
    def download_all(job_id: str, db: Session = Depends(get_db)):
        job = get_job_or_404(db, job_id)
        if job.status not in (JOB_COMPLETED, JOB_PARTIAL, JOB_FAILED):
            raise HTTPException(409, f"Job is still {job.status}. Try again later.")
        certs = db.query(Certificate).filter_by(job_id=job_id, status=CERT_SUCCESS).all()
        if not certs:
            raise HTTPException(404, "No successful certificates in this job")
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for c in certs:
                safe_name = "".join(ch if ch.isalnum() else "_" for ch in c.recipient_name)
                zf.write(c.file_path, f"{safe_name}_{c.id[:8]}.pdf")
        return Response(buf.getvalue(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="job_{job_id}.zip"'})

    return app


app = create_app()
