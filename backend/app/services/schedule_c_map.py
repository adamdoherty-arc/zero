"""Schedule C (Form 1040) Part II line mapping for ADA AI LLC's books.

Maps bookkeeper expense categories and tax-summary worksheet lines onto the
IRS Schedule C line taxonomy (instructions i1040sc, Part II). Built from spec —
no OSS library models this. Longest prefix wins so `Expenses:Software:AI` can
map differently from `Expenses:Software`. Nothing here is tax advice; the CPA
confirms line placement at filing.
"""

from __future__ import annotations

from typing import Any

# (category prefix, schedule C line, label) — longest-prefix match wins.
SCHEDULE_C_MAP: list[tuple[str, str, str]] = [
    ("Expenses:Advertising", "8", "Advertising"),
    ("Expenses:Auto", "9", "Car and truck expenses"),
    ("Expenses:Fees:Bank", "27a", "Other expenses — bank/merchant fees"),
    ("Expenses:Insurance", "15", "Insurance (other than health)"),
    ("Expenses:Legal", "17", "Legal and professional services"),
    ("Expenses:Professional", "17", "Legal and professional services"),
    ("Expenses:Office", "18", "Office expense"),
    ("Expenses:Software:AI", "27a", "Other expenses — AI/LLM services"),
    ("Expenses:Software", "27a", "Other expenses — software subscriptions"),
    ("Expenses:Cloud", "27a", "Other expenses — cloud/hosting"),
    ("Expenses:Education", "27a", "Other expenses — education/training"),
    ("Expenses:Hardware", "13", "Depreciation and section 179"),
    ("Expenses:Phone", "25", "Utilities (phone)"),
    ("Expenses:Supplies", "22", "Supplies"),
    ("Expenses:Rent", "20", "Rent or lease"),
    ("Expenses:Repairs", "21", "Repairs and maintenance"),
    ("Expenses:Travel", "24a", "Travel"),
    ("Expenses:Meals", "24b", "Deductible meals"),
    ("Expenses:Tax", "23", "Taxes and licenses"),
]

# Tax-summary worksheet line items → Schedule C lines.
WORKSHEET_LINES: dict[str, tuple[str, str]] = {
    "home_office": ("30", "Business use of home (Form 8829 / simplified)"),
    "internet": ("25", "Utilities (internet)"),
    "cell_phone": ("25", "Utilities (phone)"),
    "vehicle": ("9", "Car and truck expenses"),
    "hardware": ("13", "Depreciation and section 179"),
}

_FALLBACK = ("27a", "Other expenses")

# Sorted longest-prefix-first once at import.
_SORTED_MAP = sorted(SCHEDULE_C_MAP, key=lambda item: -len(item[0]))


def map_category(category: str) -> dict[str, str]:
    """Schedule C line + label for a bookkeeper expense category."""
    for prefix, line, label in _SORTED_MAP:
        if (category or "").startswith(prefix):
            return {"line": line, "label": label}
    return {"line": _FALLBACK[0], "label": _FALLBACK[1]}


def map_worksheet(key: str) -> dict[str, str]:
    line, label = WORKSHEET_LINES.get(key, _FALLBACK)
    return {"line": line, "label": label}


def _line_sort_key(line: str) -> tuple[int, str]:
    digits = "".join(c for c in line if c.isdigit())
    return (int(digits) if digits else 99, line)


def build_rollup(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate (line, label, amount, category) entries into per-line totals."""
    by_line: dict[str, dict[str, Any]] = {}
    for e in entries:
        bucket = by_line.setdefault(
            e["line"], {"line": e["line"], "label": e["label"], "amount": 0.0, "categories": []}
        )
        bucket["amount"] = round(bucket["amount"] + float(e["amount"] or 0.0), 2)
        if e.get("category") and e["category"] not in bucket["categories"]:
            bucket["categories"].append(e["category"])
    return sorted(by_line.values(), key=lambda b: _line_sort_key(b["line"]))
