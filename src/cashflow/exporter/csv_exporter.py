"""Export transactions to CSV with UTF-8 BOM for Vietnamese text."""

from __future__ import annotations

import csv
from pathlib import Path

from cashflow.models.transaction import ParseResult


def export_csv(result: ParseResult, output_path: str | Path) -> Path:
    """Export ParseResult to a CSV file with UTF-8 BOM encoding.

    UTF-8 BOM ensures Vietnamese characters display correctly in Excel.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    headers = [
        "Transaction Date",
        "Posting Date",
        "Description",
        "Original Amount",
        "Currency",
        "Billing Amount (VND)",
        "Type",
        "Category",
        "Merchant",
        "Card",
        "Reference",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for txn in result.transactions:
            writer.writerow([
                txn.transaction_date.strftime("%d/%m/%Y"),
                txn.posting_date.strftime("%d/%m/%Y") if txn.posting_date else "",
                txn.description,
                str(txn.original_amount),
                txn.original_currency,
                str(txn.billing_amount_vnd),
                txn.transaction_type.value,
                txn.category or "",
                txn.merchant_name or "",
                txn.card_last_four or "",
                txn.reference_number or "",
            ])

    return output_path
