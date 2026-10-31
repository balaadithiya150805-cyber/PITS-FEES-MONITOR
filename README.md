# PITS Fees Monitor

PITS Fees Monitor is a student fee collection and accounting application for
Parisutham Institute of Technology & Science. It provides a FastAPI backend,
PostgreSQL persistence, React collection and management dashboard components,
Excel student import, scholarship disbursement tracking, and Tally voucher
export.

## Features

- Search for a student by D.No and view their current-semester fee balances.
- Record fee payments with transaction history, receipt numbers, and balance
  validation.
- Track scholarship claims separately from collected fees. A pending claim does
  not reduce student arrears; disbursement records a bank transaction and
  applies the payment to the student's fee demand.
- Report on daily collections, payment modes, fee heads, counters, outstanding
  balances, departments, courses, and semesters.
- Import student records from an Excel workbook.
- Export daily transactions as Tally Receipt vouchers in XML.

## Technology

- Python 3.12
- FastAPI and Uvicorn
- SQLAlchemy 2 and PostgreSQL 15
- pandas and openpyxl for Excel ingestion
- React components styled with Tailwind CSS
- Docker Compose and NGINX for the API deployment

## Requirements

- Docker Desktop with Docker Compose, for the recommended setup; or
- Python 3.12 and a reachable PostgreSQL database for a native setup.

The React components in this repository are source files. A separate React
application with a build tool and Tailwind CSS configuration is not included.

## Run with Docker Compose

1. Copy the example environment file:

   ```powershell
   Copy-Item .env.example .env
   ```

2. Edit `.env` and set `POSTGRES_PASSWORD` to a secure local value. Do not
   commit `.env`.

3. Build and start PostgreSQL, the API, and the NGINX proxy:

   ```powershell
   docker compose up --build
   ```

4. Open the API documentation at
   [http://localhost:8000/docs](http://localhost:8000/docs). The NGINX proxy is
   available at [http://localhost:8080](http://localhost:8080).

The API waits for PostgreSQL to pass its health check. On startup, it creates
missing tables and applies the accounting schema migration. PostgreSQL data is
stored in the `postgres_data` Docker volume.

To stop the services without removing database data:

```powershell
docker compose down
```

### Docker Compose environment variables

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_DB` | `pits_fees` | PostgreSQL database name |
| `POSTGRES_USER` | `pits` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `pits_dev_password` in Compose | PostgreSQL password; set a secure value in `.env` |
| `API_PORT` | `8000` | Host port for the API |
| `NGINX_PORT` | `8080` | Host port for the NGINX proxy |
| `TZ` | `Asia/Kolkata` | Container timezone |

The password in Compose is a development fallback. Always set your own password
before using the application outside a disposable local environment.

## Run the API with a local Python environment

Create and activate a virtual environment, then install the dependencies:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Set `DATABASE_URL` to a PostgreSQL connection string before starting the API:

```powershell
$env:DATABASE_URL = "postgresql+psycopg2://USER:PASSWORD@localhost:5432/pits_fees"
python -m uvicorn main:app --host 127.0.0.1 --port 8000
```

Use your database credentials locally; do not put real credentials in source
control. The API health check is available at
[http://127.0.0.1:8000/health](http://127.0.0.1:8000/health), and interactive
OpenAPI documentation is at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

## API overview

| Method | Endpoint | Description |
| --- | --- | --- |
| `GET` | `/health` | API health check |
| `GET` | `/api/student/{d_no}` | Student details, current-semester fee balances, and payment history |
| `POST` | `/api/pay` | Record one or more fee payments using the existing collection API |
| `POST` | `/api/collections/pay` | Record a single fee-head payment with a counter number |
| `POST` | `/api/scholarship/receive` | Apply an actual receipt against a legacy scholarship |
| `POST` | `/api/scholarships/disburse` | Record an actual government scholarship disbursement against a pending claim |
| `GET` | `/api/reports/daily` | Daily collection report for the server's current date |
| `GET` | `/api/reports/daily-collections?report_date=YYYY-MM-DD` | Collections by mode, fee head, and counter for the requested date |
| `GET` | `/api/reports/outstanding-arrears` | Consolidated arrears, student payment groups, and pending scholarship records |
| `GET` | `/api/reports/outstanding-arrears?semester=2` | Arrears filtered to one semester |

Collection and scholarship receipt endpoints validate balances and record fee
updates and transactions in a database transaction. A scholarship claim remains
pending until the disbursement endpoint records the actual funds received.

## Management dashboard

`ManagementDashboard.jsx` contains a Tailwind-styled dashboard component with
daily collection and student arrears tabs. It calls the reporting endpoints,
allows filtering by collection date and semester, and provides:

- **Export to Excel (.csv):** Downloads an Excel-compatible CSV file.
- **Export to PDF:** Opens the browser's print dialog; select “Save as PDF”.

`CounterCollection.jsx` contains the student search, collection form, and
printable receipt component. These React components need to be integrated into
a separately configured React and Tailwind application.

If the frontend and API are hosted on different origins, configure
`VITE_API_BASE_URL` in the frontend build environment to the API's base URL.

## Import students from Excel

Place `students_data.xlsx` in the working directory or provide a workbook path:

```powershell
python .\import_excel.py
python .\import_excel.py .\data\students_data.xlsx
```

The workbook must contain the columns `D_No`, `Student_Name`, `Department`,
`Semester`, and `Scholarship_Category`. D.No values must be stored as text in
Excel to preserve leading zeros. The importer parses the first digit as batch,
the second as course, and the remaining two or three digits as roll number.
Existing D.No primary keys are skipped.

An earlier importer, `ingest_students.py`, supports a different workbook
layout: `D.No`, `Name`, `Department`, and `Current_Semester`.

## Export transactions to Tally

Export transactions for a date:

```powershell
python .\tally_export.py --date 2026-10-31
```

By default, the script writes
`tally_receipts_20261031.xml` in the current directory. An alternate output
path and Tally company name can be provided:

```powershell
python .\tally_export.py `
  --date 2026-10-31 `
  --output .\exports\receipts.xml `
  --company "PITS Fees Monitor"
```

Review `FEE_HEAD_LEDGER_NAMES` and `PAYMENT_MODE_LEDGER_NAMES` in
`tally_export.py` and replace the example ledger names with the exact names
configured in the target Tally company before importing vouchers. Voucher
numbers use the database transaction IDs.

## Project structure

| Path | Purpose |
| --- | --- |
| `main.py` | FastAPI application, student lookup, collections, and legacy scholarship routes |
| `reports.py` | Daily collections and arrears reporting endpoints |
| `transactions.py` | Collection and scholarship disbursement logic and accounting schema migration |
| `models.py` | SQLAlchemy student, fee demand, transaction, and scholarship models |
| `database.py` | PostgreSQL engine and SQLAlchemy session configuration |
| `CounterCollection.jsx` | React fee collection screen and printable receipt |
| `ManagementDashboard.jsx` | React management dashboard and report exports |
| `import_excel.py` | Import students from the current Excel template |
| `ingest_students.py` | Import students from the legacy Excel template |
| `tally_export.py` | Export daily transaction vouchers to Tally XML |
| `docker-compose.yml` | PostgreSQL, API, and NGINX services |

## Notes

- Keep `.env` and any database credentials out of version control.
- Ledger names are company-specific; validate the mappings before importing
  generated vouchers into Tally.
- The application has no frontend package manifest or frontend build pipeline
  in this repository.
