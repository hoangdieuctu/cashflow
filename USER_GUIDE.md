# Cashflow — User Guide

> A complete reference for using Cashflow to import statements, manage categories, track budgets, and monitor savings.

---

## Table of Contents

1. [Installation](#installation)
2. [Importing Statements](#importing-statements)
3. [The Web Dashboard](#the-web-dashboard)
4. [Transactions & Categorization](#transactions--categorization)
5. [Category Rules](#category-rules)
6. [Fund Allocation](#fund-allocation)
7. [Salary Management](#salary-management)
8. [Savings Tracker](#savings-tracker)
9. [Exporting Data](#exporting-data)
10. [Security & Passcode](#security--passcode)
11. [CLI Reference](#cli-reference)
12. [Docker Deployment](#docker-deployment)
13. [Edge Cases & Known Limitations](#edge-cases--known-limitations)

---

## Installation

```bash
git clone https://github.com/hoangdieuctu/cashflow.git
cd cashflow
python3 -m pip install -e . --break-system-packages
```

**Requirements**: Python 3.10 or higher.

**Start the dashboard**:
```bash
cashflow serve --host 127.0.0.1 --port 5000
```

---

## Importing Statements

Cashflow supports two Techcombank statement types:
- **Credit card statements** (`SÀO KÊ THẺ TÍN DỤNG`)
- **Bank account / debit card statements** (`SỔ PHỤ KIÊM PHIẾU BÁO`)

The statement type is **auto-detected** — you do not need to specify it.

### Via the Web Dashboard

1. Click **Upload** in the navigation
2. Select one or more `.pdf` files
3. Enter a password if the file is password-protected
4. Click **Upload**

After a successful import, you are redirected to the dashboard with the new transactions visible.

### Via CLI

```bash
cashflow import /path/to/statement.pdf

# Password-protected file
cashflow import /path/to/statement.pdf --password mypassword

# Custom database path
cashflow import /path/to/statement.pdf --db /data/cashflow.db
```

### How Importing Works

1. The PDF is parsed to extract transactions and statement metadata
2. The statement is stored in the database — identified by `(source_file, statement_date)`
3. If a statement with the same file and date already exists, **it is replaced** (idempotent)
4. All previously imported transactions for that statement are deleted and re-imported
5. After import, categories are **auto-assigned** in two passes:
   - Pass 1: Transactions from known merchants inherit the category used last time
   - Pass 2: Remaining uncategorized transactions are matched against your category rules

### Edge Cases

| Situation | Behaviour |
|---|---|
| PDF has no transactions | Import is skipped with a warning |
| Same file + date imported again | Existing data is replaced |
| Password-protected, no password given | Error: import fails |
| Wrong password | Error: import fails |
| Bank account PDF with unreadable layout | Warning shown; affected transactions have amount=0, type=debit |

---

## The Web Dashboard

Open [http://127.0.0.1:5000](http://127.0.0.1:5000) after starting `cashflow serve`.

### Filtering Transactions

The dashboard supports multiple filters, all combined with AND:

| Filter | Values | Notes |
|---|---|---|
| **Period** | `YYYY` or `YYYY-MM` | Defaults to current year if not set. Set to blank for all time |
| **Date range** | `YYYY-MM-DD` start / end | Overrides period if both set |
| **Type** | `debit` / `credit` | Debit = money out; Credit = money in |
| **Category** | Any category name | Use `__uncategorized__` to find uncategorized transactions |
| **Statement** | Specific statement | Dropdown from all imported statements |
| **Statement type** | `credit_card` / `bank_account` | Filter by source statement type |
| **Search** | Free text | Matches anywhere in the description |

### Pagination

Transactions are shown 50 per page. Use the page controls at the bottom to navigate.

### Summary Cards

- **Total transactions** — count for the current filter
- **Total debit** — total spending (money out) in VND
- **Total credit** — total income / refunds (money in) in VND

### Charts

- **Monthly spending trend** — debit by month
- **Category breakdown** — spending per category for the period
- **Fund allocation vs. actual** — how much you allocated vs. spent per fund

---

## Transactions & Categorization

### What Is a Category?

A category is a free-text label you assign to a transaction (e.g., `Food`, `Transport`, `Salary`). Categories drive:
- Spending breakdowns in the dashboard
- Fund allocation — which fund "owns" which expenses
- Salary detection for automatic topups

### Assigning a Category

Click on any transaction row in the dashboard and update its category inline.

When assigning a category you can choose to **apply to all transactions from the same merchant** — this bulk-updates every transaction that shares the same merchant name.

### How Auto-Categorization Works

Every time you import a new statement:
1. **Merchant history lookup**: If a merchant was previously categorized, all new transactions from that merchant get the same category automatically
2. **Rule matching**: Any remaining uncategorized transactions are checked against your category rules (in priority order — highest first)

Only the **first matching rule** is applied per transaction.

---

## Category Rules

Rules let you automatically categorize transactions based on patterns in the description.

### Rule Types

| Type | Behaviour | Example |
|---|---|---|
| `contains` | Matches if the description contains the pattern (case-insensitive LIKE) | `"CIRCLE K"` matches `"CIRCLE K STORE 12"` |
| `endswith` | Matches if the description ends with the pattern | `"VN"` matches `"GRAB VN"` |

### Priority

Rules are applied in **priority order** (higher number = applied first). If two rules could match the same transaction, only the higher-priority rule applies.

### Managing Rules

Go to **Rules** in the navigation to:
- Add a new rule (match type, pattern, category, priority)
- Edit an existing rule
- Delete a rule
- See how many transactions each rule has matched
- **Apply all rules** to currently uncategorized transactions

### Apply Rules

The **Apply Rules** button re-runs all rules against every transaction that has no category. It does **not** overwrite existing categories.

---

## Fund Allocation

Funds let you divide your salary into named budget buckets and track spending against each one.

### How Funds Work

1. Create a fund (e.g., "Living Expenses") with a **percentage** of your salary (e.g., 50%)
2. Assign **categories** to the fund (e.g., "Food", "Rent", "Utilities")
3. When you record a salary entry, the fund receives `salary × percentage` as a topup
4. The fund balance decreases as transactions in its categories are spent

### Fund Balance Calculation

```
Fund balance = override_balance   (if manually set)
             = total_allocated - total_spent + savings_principal  (otherwise)

total_allocated = sum of all salary topups for this fund (all-time)
total_spent     = sum of all debit transactions in the fund's categories (all-time)
```

> **Note**: The balance calculation is always **all-time**, not period-filtered. The period filter on the dashboard only affects the "spent this period" display, not the balance.

### Category Ownership

Each category can belong to **only one fund**. If you assign a category to a new fund, it is automatically removed from any fund that previously owned it.

### Manual Balance Override

If your calculated balance is out of sync (e.g., after a cash reconciliation), you can set a **manual override balance** on any fund. This replaces the calculated balance. Future salary topups are added on top of the override amount.

### Fund History

Click a fund's history button to see a full timeline:
- `topup` — salary allocations
- `manual` — manual balance overrides
- `spend` — individual transactions
- `saving` — linked savings accounts

---

## Salary Management

### Recording a Salary Entry

Go to **Funds**, find the Salary section, and add an entry with:
- **Year-Month** (YYYY-MM format, e.g., `2026-03`)
- **Amount** (in VND)

> Salary entries **cannot be deleted** once added. If you made a mistake, use a manual fund balance override to correct the fund amounts.

### Automatic Fund Topup

When you add a salary entry, each fund is **automatically topped up** by `salary × fund_percentage / 100`.

If a fund has a manual override balance set, the topup is added to the override amount (not the calculated total).

### Importing Salary from Transactions

On the Funds page, use **Import from Transactions** to see credit transactions already categorized as `Salary`. These appear grouped by month and can be added as salary entries in one click. Months already imported are marked as already imported.

---

## Savings Tracker

### Saving Types

| Type | Behaviour |
|---|---|
| **Fixed** | No withdrawals. Interest calculated on full principal for full term |
| **Flexible** | Partial withdrawals allowed. Interest calculated in segments between withdrawals |

### Rollover Types

| Type | What Happens at Maturity |
|---|---|
| `withdraw` | Saving ends. Balance returned to fund or withdrawn |
| `rollover_principal` | Principal is reinvested. Interest is withdrawn |
| `rollover_full` | Principal + interest are reinvested |

### Interest Calculation

**Fixed savings**:
```
interest = principal × (annual_rate / 100) × (actual_days / 365)
```

**Flexible savings** (with withdrawals):
- The term is split into segments at each withdrawal date
- Each segment: `remaining_principal × (annual_rate / 100) × (segment_days / 365)`
- Total interest = sum of all segments
- `current_principal = principal − sum(all withdrawals)`

### Rollover Projections

For savings with rollover enabled, Cashflow shows a projection table for up to **60 terms** showing cumulative principal and interest over time.

### Status

- **Active** — maturity date is in the future
- **Matured** — maturity date has passed (shown with a warning)

Savings maturing in the **current calendar month** are highlighted with a badge in the navigation.

### Linking Savings to Funds

When you create a saving, you can optionally link it to a fund. The saving's principal then contributes to that fund's balance.

---

## Exporting Data

### Via CLI

```bash
# Export to Excel (default)
cashflow parse statement.pdf

# Export to all formats
cashflow parse statement.pdf --output-format all --output-dir ./exports

# Specific format
cashflow parse statement.pdf --output-format csv
cashflow parse statement.pdf --output-format json
```

### Output Formats

| Format | Notes |
|---|---|
| **Excel** (.xlsx) | Two sheets: Transactions + Summary. Headers formatted, amounts with thousands separator, frozen header row |
| **CSV** (.csv) | UTF-8 with BOM (opens correctly in Excel with Vietnamese characters) |
| **JSON** (.json) | Full structure with metadata, UTF-8, 2-space indent, Vietnamese characters preserved |

---

## Security & Passcode

### Enabling a Passcode

Go to **Settings** and set a **6-digit numeric passcode**. Once enabled:
- Every session requires the passcode to access the dashboard
- Sessions expire after **5 minutes of inactivity**
- The passcode is stored as a SHA-256 hash — never in plain text

### Changing or Disabling

- **Change**: You must enter the current passcode before setting a new one
- **Disable**: You must enter the current passcode to disable it

### Locking Manually

Click **Lock** in the navigation (or visit `/lock/now`) to immediately end your session.

---

## CLI Reference

```
cashflow [COMMAND] [OPTIONS]
```

### `cashflow import`

Import a PDF statement into the database.

```bash
cashflow import <pdf_path> [--db PATH] [--password PASS]
```

### `cashflow parse`

Parse a PDF and export to file (does not store in database).

```bash
cashflow parse <pdf_path> \
  [--output-format excel|csv|json|all] \
  [--output-dir PATH] \
  [--password PASS]
```

### `cashflow query`

Query transactions from the database.

```bash
cashflow query \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD] \
  [--type debit|credit] \
  [--search TEXT] \
  [--limit 50] \
  [--summary] \
  [--db PATH]
```

`--summary` shows monthly aggregate totals instead of individual transactions.

### `cashflow serve`

Start the web dashboard.

```bash
cashflow serve \
  [--host 127.0.0.1] \
  [--port 5000] \
  [--debug] \
  [--db PATH]
```

### `cashflow convert`

Convert PDF pages to images.

```bash
cashflow convert <pdf_path> \
  [--output-dir PATH] \
  [--dpi 300] \
  [--format png|jpeg] \
  [--pages 1,2,3] \
  [--password PASS]
```

Pages are **1-indexed** (e.g., `--pages 1,3` converts pages 1 and 3).

---

## Docker Deployment

### Quick Start

```bash
docker compose up
```

This starts the dashboard on port 5000 using the image `hoangdieuctu/cashflow-pub`.

### Persistent Data

Mount a local directory to `/data` to persist the database across container restarts:

```yaml
volumes:
  - ./data:/data
```

### Manual Run

```bash
docker run -p 5000:5000 -v $(pwd)/data:/data hoangdieuctu/cashflow-pub:1.0.9
```

The container initializes the database on first run and runs as a non-root user.

---

## Edge Cases & Known Limitations

### Parsing

| Situation | Behaviour |
|---|---|
| PDF is encrypted, no password provided | Import fails with an error |
| PDF text cannot be extracted | Warning logged; OCR layer required |
| Bank statement columns in unexpected positions | Y-coordinate thresholds are hardcoded to Techcombank layout; other banks may not parse correctly |
| Two-digit years (e.g., 25/12/25) | Treated as 2025 if year < 50, else 1900s |
| Amount formatting: `1.234.567` | Parsed as 1,234,567 VND (dot = thousands separator) |
| Amount formatting: `1.234` | Parsed as 1.234 (dot = decimal) if the right side has fewer than 3 digits |
| Negative or parenthesized amounts | Parsed correctly: `(500.000)` and `-500.000` both = -500,000 |
| Multi-currency transactions | Original currency is stored, but no conversion is applied — billing_amount_vnd is taken directly from the statement |

### Database

| Situation | Behaviour |
|---|---|
| Re-importing the same statement | Previous transactions are deleted and replaced |
| Deleting a salary entry | Not permitted (API returns 403) |
| Deleting a fund | Cascades — removes fund categories and balance log entries |
| Deleting a saving | Cascades — removes all withdrawal records |
| Category removed from a fund | Existing transactions keep their category; only fund assignment changes |

### Categories & Rules

| Situation | Behaviour |
|---|---|
| Transaction matches multiple rules | Only the highest-priority rule applies |
| Two rules with same priority | The one with the lower database ID applies |
| `apply_rules` on already-categorized transactions | Skipped — only uncategorized transactions are affected |
| Category assigned to a second fund | Removed from the first fund automatically |

### Savings

| Situation | Behaviour |
|---|---|
| Withdrawal amount > remaining principal | No validation — you can over-withdraw (resulting in negative current_principal) |
| Rollover projections | Limited to 60 terms maximum |
| Flexible saving with no withdrawals | Interest calculated as if it were a fixed saving |

### General

| Situation | Behaviour |
|---|---|
| Multiple filters on the dashboard | All filters are combined with AND (not OR) |
| Period filter vs. balance | Fund balance is always all-time; period only filters "spent this period" display |
| Passcode session timeout | 5 minutes of inactivity — any page visit resets the timer |
| File upload size limit | 50 MB per request (configurable via Flask MAX_CONTENT_LENGTH) |
