"""Minimal CSV formatter for Arke S051 V1.

RFC 4180-compliant writer for deterministic single/multi-row exports.
"""

from __future__ import annotations

import csv
import io
from typing import Any


def format_csv_header_only(columns: list[str]) -> str:
    """Return a CSV string containing only the header row."""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns)
    writer.writeheader()
    return buf.getvalue()


def format_csv_rows(columns: list[str], rows: list[dict[str, Any]]) -> str:
    """Return CSV text for rows using deterministic column order.

    Missing values become empty cells, extra keys are ignored.
    """
    if not columns:
        return ""

    if not rows:
        return format_csv_header_only(columns)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        normalized: dict[str, Any] = {k: row.get(k, "") for k in columns}
        writer.writerow(normalized)
    return buf.getvalue()
