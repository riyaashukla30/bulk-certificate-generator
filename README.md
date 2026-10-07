# Bulk Certificate Generator

A backend API that accepts a certificate generation request for a list of recipients, validates the data,
generates a certificate (PDF) for each valid recipient using a single predefined template, tracks the status
of the job, and lets the client retrieve the generated certificates.

**Technology:** Python 3.10+, FastAPI, SQLAlchemy with SQLite (relational database), ReportLab (PDF generation), pytest.

---

## How to set up the project

```bash
git clone https://github.com/riyaashukla30/bulk-certificate-generator.git
cd bulk-certificate-generator

python -m venv venv
source venv/bin/activate          # Windows (PowerShell): venv\Scripts\Activate.ps1
                                  # Windows (CMD):        venv\Scripts\activate

pip install -r requirements.txt
```

No separate database setup is needed; the tables are created automatically on the first start.

Optional environment variables:

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy database URL (for example PostgreSQL) |
| `OUTPUT_DIR` | `generated` | Folder where the generated PDF files are stored |

---

## How to run the application

```bash
uvicorn app.main:app --reload
```

- API base URL: `http://127.0.0.1:8000`
- Interactive API documentation (Swagger UI): `http://127.0.0.1:8000/docs`

---

## How to run tests

```bash
pytest -v
```

The tests use a temporary database and a temporary output folder, so they do not touch real data.
They cover: creating a generation job, input validation, certificate generation, job status/progress,
handling of an individual certificate failure, and retrieving generated certificates.

---

## How to submit a certificate generation request

**Endpoint:** `POST /jobs`

```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d @sample_request.json
```

(On Windows PowerShell use `curl.exe` instead of `curl`.)

Example request body (`sample_request.json`):

```json
{
  "event_name": "Python Workshop 2026",
  "issued_by": "VIT Bhopal Tech Club",
  "issue_date": "2026-10-01",
  "recipients": [
    {"name": "Riya Shukla", "email": "riya@example.com"},
    {"name": "Aman Verma", "email": "aman@example.com", "achievement": "for winning 1st prize in"},
    {"name": "", "email": "invalid-email"}
  ]
}
```

| Field | Rules |
|---|---|
| `event_name` | required, 1-200 characters |
| `issued_by` | required, 1-100 characters |
| `issue_date` | required, format `YYYY-MM-DD` |
| `recipients` | required, 1 to 1000 items |
| `recipients[].name` | required, 1-100 characters |
| `recipients[].email` | required, valid email format |
| `recipients[].achievement` | optional text printed on the certificate (default: "for successful participation in") |

The API replies immediately with `202 Accepted` and a `job_id`. The certificates are generated in the background.

```json
{
  "job_id": "3f2c9a1e-...",
  "status": "pending",
  "event_name": "Python Workshop 2026",
  "total": 3,
  "succeeded": 0,
  "failed": 1,
  "pending": 2,
  "certificates_url": "/jobs/3f2c9a1e-.../certificates",
  "download_all_url": "/jobs/3f2c9a1e-.../download"
}
```

**Checking the progress / result of the request**

```bash
# overall status and counts
curl http://127.0.0.1:8000/jobs/<job_id>

# status of every certificate (supports ?status=success|failed|pending, ?limit=, ?offset=)
curl "http://127.0.0.1:8000/jobs/<job_id>/certificates"
curl "http://127.0.0.1:8000/jobs/<job_id>/certificates?status=failed"
```

- Job status values: `pending`, `processing`, `completed`, `completed_with_errors`, `failed`.
- Certificate status values: `pending`, `success`, `failed`.
- A failed certificate carries an `error` message, for example
  `Validation error: name must not be empty; email has an invalid format`.

---

## How to retrieve generated certificates

```bash
# a single certificate (PDF); the URL is the "download_url" field in the certificates list
curl -o certificate.pdf http://127.0.0.1:8000/certificates/<certificate_id>/download

# all successful certificates of a job as one ZIP file
curl -o certificates.zip http://127.0.0.1:8000/jobs/<job_id>/download
```

- Downloading a failed or not-yet-generated certificate returns `409 Conflict`.
- The ZIP endpoint returns `409` while the job is still being processed, and `404` if the job has no successful certificates.
- An unknown job or certificate ID returns `404`.

---

## Important implementation/design decisions

**Bulk processing: background processing instead of synchronous processing.**
One request can contain up to 1000 recipients, and generating that many PDFs inside the request could take long
and hit HTTP timeouts. Therefore `POST /jobs` saves the job, returns `202 Accepted` immediately, and the PDFs are
generated in the background using FastAPI `BackgroundTasks`. The client polls `GET /jobs/{job_id}` to see the progress.
Trade-off: background tasks run inside the server process, so a server restart can interrupt a running job.
For production, a task queue such as Celery or RQ with Redis would be the next step; it was not used here to keep the
setup simple and free of extra infrastructure. Bulk generation is supported in one request, so the client never has
to make one API call per certificate.

**Validation (two levels).**
- Request level: a missing or invalid `event_name`, `issued_by` or `issue_date`, or an empty / oversized recipient list,
  rejects the whole request with `422`.
- Recipient level: every recipient is validated individually. An invalid recipient does not reject the request;
  it is stored as a `failed` certificate with a clear error message, and all valid recipients are still processed.

**Failure handling.**
Each certificate is generated inside its own `try/except` and committed to the database right after it is processed.
A failure in one certificate never stops the others, and the progress is visible while the job is running.
The final job status is `completed` when all certificates succeeded, `completed_with_errors` when some failed, and
`failed` when all failed. The job status and the per-certificate list identify exactly which generations succeeded and which failed.

**Certificate template.**
A single predefined landscape A4 template drawn with ReportLab (border, title, recipient name, achievement text,
event name, date and issuer). There is no template editor and no support for multiple designs, as per the requirements.

**Database design.**
Two tables: `jobs` (one) and `certificates` (many). A certificate row stores the recipient data, its position in the
request, its status, the file path and the error message. `certificates.job_id` is indexed. Job counts are always
computed from the certificate rows, so the counts and the job status cannot get out of sync.

**File storage.**
PDFs are saved on disk at `generated/<job_id>/<certificate_id>.pdf`; the database stores only the file path.

**Listing and pagination.**
The certificates list supports `limit` (maximum 500), `offset` and a `status` filter, because a job can be large.
Items are returned in the same order in which the recipients were submitted.

**Testability.**
The application is created through a `create_app(db_url, output_dir)` factory, so every test gets its own temporary
database and output folder.

**Known limitations.**
The built-in Helvetica font is used, so non-Latin names (for example Hindi) would need a Unicode TTF font to be registered.
There is no authentication and no duplicate-recipient detection.
