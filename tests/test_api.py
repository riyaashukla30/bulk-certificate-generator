import io
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app import services
from app.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_url=f"sqlite:///{tmp_path}/test.db", output_dir=tmp_path / "out")
    # TestClient background task ko response ke saath hi chala deta hai
    return TestClient(app)


def make_payload(recipients):
    return {"event_name": "Python Workshop", "issued_by": "Tech Club",
            "issue_date": "2026-10-01", "recipients": recipients}


GOOD = [{"name": "Riya Shukla", "email": "riya@example.com"},
        {"name": "Aman Verma", "email": "aman@example.com", "achievement": "for winning 1st prize in"}]


# ---- 1. Creating a generation job ----
def test_create_job_returns_202_with_job_id(client):
    r = client.post("/jobs", json=make_payload(GOOD))
    assert r.status_code == 202
    body = r.json()
    assert body["job_id"]
    assert body["total"] == 2


# ---- 2. Input validation ----
def test_empty_recipient_list_rejected(client):
    assert client.post("/jobs", json=make_payload([])).status_code == 422


def test_missing_event_name_rejected(client):
    payload = make_payload(GOOD)
    del payload["event_name"]
    assert client.post("/jobs", json=payload).status_code == 422


def test_invalid_recipient_marked_failed_but_valid_ones_succeed(client):
    recipients = GOOD + [{"name": "", "email": "x@example.com"},
                         {"name": "No Email Guy", "email": "not-an-email"}]
    job_id = client.post("/jobs", json=make_payload(recipients)).json()["job_id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["total"] == 4
    assert job["succeeded"] == 2
    assert job["failed"] == 2
    assert job["status"] == "completed_with_errors"

    failed = client.get(f"/jobs/{job_id}/certificates", params={"status": "failed"}).json()
    assert len(failed["items"]) == 2
    assert all("Validation error" in i["error"] for i in failed["items"])


def test_all_invalid_recipients_job_fails(client):
    job_id = client.post("/jobs", json=make_payload([{"name": "", "email": "bad"}])).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "failed"


# ---- 3. Certificate generation ----
def test_pdf_is_generated_with_recipient_name(tmp_path):
    out = tmp_path / "c.pdf"
    from datetime import date
    services.generate_certificate_pdf(out, "Riya Shukla", "Python Workshop", "Tech Club",
                                      date(2026, 10, 1), None)
    assert out.exists()
    text = PdfReader(str(out)).pages[0].extract_text()
    assert "Riya Shukla" in text
    assert "Python Workshop" in text


# ---- 4. Job status / progress ----
def test_job_status_completed(client):
    job_id = client.post("/jobs", json=make_payload(GOOD)).json()["job_id"]
    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed"
    assert (job["total"], job["succeeded"], job["failed"], job["pending"]) == (2, 2, 0, 0)


def test_unknown_job_returns_404(client):
    assert client.get("/jobs/does-not-exist").status_code == 404


# ---- 5. Individual certificate failure ----
def test_one_generation_failure_does_not_stop_others(client, monkeypatch):
    real = services.generate_certificate_pdf

    def flaky(path, name, *args, **kwargs):
        if name == "Aman Verma":
            raise RuntimeError("font error")
        return real(path, name, *args, **kwargs)

    monkeypatch.setattr(services, "generate_certificate_pdf", flaky)
    job_id = client.post("/jobs", json=make_payload(GOOD)).json()["job_id"]

    job = client.get(f"/jobs/{job_id}").json()
    assert job["status"] == "completed_with_errors"
    assert job["succeeded"] == 1 and job["failed"] == 1

    failed = client.get(f"/jobs/{job_id}/certificates", params={"status": "failed"}).json()["items"]
    assert failed[0]["recipient_name"] == "Aman Verma"
    assert "font error" in failed[0]["error"]


# ---- 6. Retrieving generated certificates ----
def test_download_single_certificate(client):
    job_id = client.post("/jobs", json=make_payload(GOOD)).json()["job_id"]
    items = client.get(f"/jobs/{job_id}/certificates").json()["items"]
    r = client.get(items[0]["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")


def test_download_all_as_zip(client):
    job_id = client.post("/jobs", json=make_payload(GOOD)).json()["job_id"]
    r = client.get(f"/jobs/{job_id}/download")
    assert r.status_code == 200
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        assert len(zf.namelist()) == 2


def test_failed_certificate_cannot_be_downloaded(client):
    job_id = client.post("/jobs", json=make_payload([{"name": "", "email": "bad"}] + GOOD)).json()["job_id"]
    failed = client.get(f"/jobs/{job_id}/certificates", params={"status": "failed"}).json()["items"][0]
    assert failed["download_url"] is None
    r = client.get(f"/certificates/{failed['certificate_id']}/download")
    assert r.status_code == 409


def test_pagination(client):
    many = [{"name": f"User {i}", "email": f"u{i}@example.com"} for i in range(25)]
    job_id = client.post("/jobs", json=make_payload(many)).json()["job_id"]
    page = client.get(f"/jobs/{job_id}/certificates", params={"limit": 10, "offset": 20}).json()
    assert page["total"] == 25 and len(page["items"]) == 5
