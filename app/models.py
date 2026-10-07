import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

# Job statuses
JOB_PENDING = "pending"
JOB_PROCESSING = "processing"
JOB_COMPLETED = "completed"
JOB_PARTIAL = "completed_with_errors"
JOB_FAILED = "failed"

# Certificate statuses
CERT_PENDING = "pending"
CERT_SUCCESS = "success"
CERT_FAILED = "failed"


def new_id() -> str:
    return str(uuid.uuid4())


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    event_name: Mapped[str] = mapped_column(String(200))
    issued_by: Mapped[str] = mapped_column(String(100))
    issue_date: Mapped[date] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(30), default=JOB_PENDING)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )

    certificates: Mapped[list["Certificate"]] = relationship(back_populates="job")


class Certificate(Base):
    __tablename__ = "certificates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"), index=True)
    recipient_name: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    recipient_email: Mapped[Optional[str]] = mapped_column(String(254), nullable=True)
    achievement: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=CERT_PENDING)
    file_path: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    job: Mapped["Job"] = relationship(back_populates="certificates")
