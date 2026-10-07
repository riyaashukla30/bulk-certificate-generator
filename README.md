# Bulk Certificate Generator

Backend API jo ek request mein recipients ki list leta hai, har valid recipient ke liye PDF certificate
generate karta hai (ek predefined template se), progress track karta hai, aur certificates download karne deta hai.

**Stack:** Python 3.10+, FastAPI, SQLAlchemy (SQLite by default), ReportLab, pytest

## 1. Setup
```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Run
```bash
uvicorn app.main:app --reload
```
- API: http://127.0.0.1:8000
- Interactive docs (Swagger): http://127.0.0.1:8000/docs

Optional environment variables:
| Variable | Default | Meaning |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./certificates.db` | Any SQLAlchemy URL (e.g. PostgreSQL) |
| `OUTPUT_DIR` | `generated` | PDF files yahan save hote hain |

## 3. Run tests
```bash
pytest -v
```

## 4. Submit a generation request
```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d @sample_request.json
```
Response (`202 Accepted`):
```json
{
  "job_id": "3f2c...",
  "status": "processing",
  "event_name": "Python Workshop 2026",
  "total": 3, "succeeded": 0, "failed": 1, "pending": 2,
  "certificates_url": "/jobs/3f2c.../certificates",
  "download_all_url": "/jobs/3f2c.../download"
}
```

**Request fields**
| Field | Rules |
|---|---|
| `event_name` | required, 1-200 chars |
| `issued_by` | required, 1-100 chars |
| `issue_date` | required, `YYYY-MM-DD` |
| `recipients` | required, 1 to 1000 items |
| `recipients[].name` | required, 1-100 chars |
| `recipients[].email` | required, valid email format |
| `recipients[].achievement` | optional text printed on the certificate (default: "for successful participation in") |

## 5. Check progress
```bash
curl http://127.0.0.1:8000/jobs/<job_id>
```
Job status values: `pending`, `processing`, `completed`, `completed_with_errors`, `failed`.
Response mein `total`, `succeeded`, `failed`, `pending` counts milte hain.

List certificates (per-recipient status + error reason), with filter and pagination:
```bash
curl "http://127.0.0.1:8000/jobs/<job_id>/certificates?status=failed&limit=50&offset=0"
```

## 6. Retrieve certificates
```bash
# ek certificate (PDF)
curl -o cert.pdf http://127.0.0.1:8000/certificates/<certificate_id>/download

# poore job ke saare successful certificates (ZIP)
curl -o certs.zip http://127.0.0.1:8000/jobs/<job_id>/download
```
- Failed certificate download karne par `409` milta hai.
- Job abhi chal raha ho to ZIP endpoint `409` deta hai ("try again later").

## API summary
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/jobs` | Bulk job create (202) |
| GET | `/jobs/{job_id}` | Job status + counts |
| GET | `/jobs/{job_id}/certificates` | Per-certificate status/errors (filter + pagination) |
| GET | `/certificates/{id}/download` | Single PDF |
| GET | `/jobs/{job_id}/download` | ZIP of all successful PDFs |

## Design decisions

**1. Background processing (not synchronous).**
Ek request mein 1000 recipients ho sakte hain. Agar sab kuch request ke andar karte, to client ko lamba wait
karna padta aur HTTP timeout ka risk hota. Isliye `POST /jobs` job save karke turant `202` return karta hai
aur PDFs FastAPI `BackgroundTasks` se background mein banti hain. Client `GET /jobs/{id}` se progress poll karta hai.
*Trade-off:* BackgroundTasks server process ke andar chalte hain, to server restart hone par pending job ruk sakta hai.
Production mein Celery/RQ + Redis use karna chahiye (neeche "Future improvements").
Is assignment ke scope ke liye BackgroundTasks simple hai aur extra infrastructure nahi chahiye.

**2. Two-level validation.**
- *Request level* (Pydantic): `event_name`, `issue_date`, empty/too-large recipient list -> poori request `422` se reject.
- *Recipient level*: har recipient alag validate hota hai. Galat recipient poori request ko reject nahi karta;
  uska certificate row `failed` + error message ke saath save hota hai, baaki valid recipients process hote hain.

**3. Failure isolation.**
Har certificate apne `try/except` mein generate hota hai aur har certificate ke baad DB commit hota hai.
Ek fail hone se baaki nahi rukte, aur progress live dikhta hai. Final job status:
sab success -> `completed`; kuch fail -> `completed_with_errors`; sab fail -> `failed`.

**4. Database schema.**
`jobs` (1) -> `certificates` (many). Certificate row mein recipient data, status, file path, error store hota hai.
`certificates.job_id` par index hai. Job counts hamesha certificates se compute hote hain, to counts aur
status kabhi out-of-sync nahi hote.

**5. Storage.**
PDFs disk par `generated/<job_id>/<certificate_id>.pdf` mein save hoti hain, DB mein sirf path.

**6. Pagination.**
Certificates list `limit` (max 500) aur `offset` support karti hai, kyunki job bahut bada ho sakta hai.

**7. Testability.**
`create_app(db_url, output_dir)` factory se tests har baar alag temp DB use karte hain.

## Known limitations / future improvements
- Celery/RQ + Redis for durable, restart-safe, parallel processing.
- Standard Helvetica font use hota hai; Hindi jaise non-Latin names ke liye Unicode TTF font register karna padega.
- Authentication aur duplicate-recipient detection nahi hai.
- Email se certificates bhejna (recipient ka email already stored hai) future feature ho sakta hai.
