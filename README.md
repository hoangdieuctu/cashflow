<p align="center">
  <img src="https://img.shields.io/badge/version-1.0.9-0a0a0a?style=for-the-badge&labelColor=0a0a0a&color=00d4aa" alt="version"/>
  <img src="https://img.shields.io/badge/python-3.10+-0a0a0a?style=for-the-badge&labelColor=0a0a0a&color=00d4aa" alt="python"/>
  <img src="https://img.shields.io/badge/license-MIT-0a0a0a?style=for-the-badge&labelColor=0a0a0a&color=00d4aa" alt="license"/>
  <img src="https://img.shields.io/badge/tests-55%20passing-0a0a0a?style=for-the-badge&labelColor=0a0a0a&color=00d4aa" alt="tests"/>
</p>

<h1 align="center">
  <br/>
  💸 Cashflow
  <br/>
</h1>

<p align="center">
  <strong>Parse · Categorize · Analyze · Save</strong><br/>
  A personal finance CLI + web dashboard for Techcombank PDF statements
</p>

---

## What It Does

**Cashflow** turns your Techcombank PDF statements into actionable financial data. Drop in a credit card or bank account statement, and it extracts every transaction, categorizes your spending, tracks savings, and visualizes everything through a clean web dashboard.

```
PDF Statement  ──▶  Parse  ──▶  SQLite DB  ──▶  Web Dashboard
                                           ──▶  Excel / CSV / JSON
```

---

## Features

| Feature | Description |
|---|---|
| **Smart PDF Parsing** | Auto-detects credit card vs. bank account statements; OCR fallback |
| **Transaction Categorization** | Rule-based engine with pattern matching; bulk assign by merchant |
| **Fund Allocation** | Divide salary into named budget buckets (food, transport, etc.) |
| **Savings Tracker** | Fixed & flexible savings with interest calculation and maturity alerts |
| **Web Dashboard** | Filter, search, chart, and paginate your transactions |
| **Multi-format Export** | Export to Excel, CSV (UTF-8 BOM), or JSON |
| **Passcode Lock** | Optional 6-digit PIN with SHA-256 hashing and session timeout |
| **Docker Ready** | Single-command deploy with persistent volume support |

---

## Quick Start

### Install

```bash
git clone https://github.com/hoangdieuctu/cashflow.git
cd cashflow
python3 -m pip install -e . --break-system-packages
```

### Import a Statement

```bash
cashflow import /path/to/statement.pdf
```

### Launch the Dashboard

```bash
cashflow serve --host 127.0.0.1 --port 5000
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

### Or Run with Docker

```bash
docker compose up
```

---

## CLI Reference

```
cashflow [COMMAND] [OPTIONS]
```

| Command | Description |
|---|---|
| `import <pdf>` | Parse PDF and store transactions in the database |
| `parse <pdf>` | Parse PDF and export to file (Excel/CSV/JSON) |
| `query` | Query transactions from the database |
| `serve` | Start the web dashboard |
| `convert <pdf>` | Convert PDF pages to PNG/JPEG images |
| `--version` | Show current version |

### Examples

```bash
# Import a password-protected statement
cashflow import statement.pdf --password mypass

# Export to all formats
cashflow parse statement.pdf --output-format all --output-dir ./exports

# Query last month's debits
cashflow query --start-date 2026-02-01 --end-date 2026-02-28 --type debit

# Start server on custom port
cashflow serve --host 0.0.0.0 --port 8080
```

---

## Web Dashboard

The dashboard provides a full-featured interface for your financial data:

- **Dashboard** — Spending overview, monthly trends, category breakdowns, transaction list with filters
- **Upload** — Batch import PDF statements
- **Rules** — Create and manage auto-categorization patterns
- **Funds** — Budget allocation: assign salary percentages and expense categories to named funds
- **Savings** — Track fixed/flexible savings accounts with interest projections
- **Settings** — Configure passcode protection

### API Endpoints

The web app also exposes a JSON API:

```
GET  /api/transactions          List transactions (with filters)
GET  /api/summary               Spending summary
POST /api/rules                 Create categorization rule
POST /api/rules/apply           Apply rules to uncategorized transactions
POST /api/transaction/:id/category  Update transaction category
POST /api/funds                 Create budget fund
POST /api/savings               Create savings account
POST /api/settings/passcode     Configure passcode
```

---

## Project Structure

```
src/cashflow/
├── cli.py              # Click CLI entry point
├── config.py           # Constants & paths
├── models/             # Pydantic data models
├── parser/             # PDF parsing (credit card + bank account)
├── converter/          # PDF → image conversion
├── exporter/           # Excel, CSV, JSON exporters
└── web/
    ├── app.py          # Flask app factory + auth middleware
    ├── routes.py       # All route handlers
    ├── templates/      # Jinja2 HTML templates
    └── static/         # Assets
```

---

## Database Schema

Cashflow uses SQLite (`cashflow.db`) with 10 tables:

```
statements          ─── transactions
category_rules          funds ─── fund_categories
salary_entries              └── fund_balance_log
savings ─── saving_withdrawals
settings
```

Key fields on `transactions`: `transaction_date`, `description`, `billing_amount_vnd`, `transaction_type`, `category`, `merchant_name`, `card_last_four`, `running_balance`

---

## Configuration

| Constant | Default | Description |
|---|---|---|
| `DATABASE_PATH` | `data/cashflow.db` | SQLite database location |
| `DEFAULT_DPI` | `300` | PDF-to-image resolution |
| `DEFAULT_IMAGE_FORMAT` | `png` | PDF-to-image format |
| `OUTPUT_DIR` | `data/output/` | Default export directory |

Override the database path at runtime:

```bash
cashflow serve --db /custom/path/cashflow.db
cashflow import statement.pdf --db /custom/path/cashflow.db
```

---

## Development

```bash
# Install with dev dependencies
python3 -m pip install -e ".[dev]" --break-system-packages

# Run tests
python3 -m pytest

# Run with coverage
python3 -m pytest --cov=cashflow
```

**55 tests** across parsing, database, exporters, and normalizers — all passing.

---

## Docker

```bash
# Using Docker Compose (recommended)
docker compose up

# Manual run
docker run -p 5000:5000 -v $(pwd)/data:/data hoangdieuctu/cashflow-pub:1.0.9
```

The container:
- Exposes port `5000`
- Persists data at `/data` (mount a volume)
- Initializes the database on first run
- Runs as a non-root user

---

## Dependencies

| Package | Purpose |
|---|---|
| `PyMuPDF >= 1.24` | PDF text extraction |
| `pdfplumber >= 0.11` | PDF table parsing |
| `pydantic >= 2.0` | Data validation & models |
| `click >= 8.1` | CLI framework |
| `Flask >= 3.0` | Web dashboard |
| `openpyxl >= 3.1` | Excel export |
| `pandas >= 2.0` | Data processing |

---

## Supported Statements

Currently supports **Techcombank** (Vietnam):
- Credit card statements (`SÀO KÊ THẺ TÍN DỤNG`)
- Bank account / debit card statements

Both text-based and scanned (OCR) PDFs are supported.

---

## License

MIT © [hoangdieuctu](https://github.com/hoangdieuctu)
