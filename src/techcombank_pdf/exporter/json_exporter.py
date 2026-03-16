"""Export transactions to JSON using Pydantic serialization."""

from __future__ import annotations

import json
from pathlib import Path

from techcombank_pdf.models.transaction import ParseResult


def export_json(result: ParseResult, output_path: str | Path) -> Path:
    """Export ParseResult to a JSON file.

    Uses Pydantic's model serialization for proper date/Decimal handling.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = result.model_dump(mode="json")

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    return output_path
