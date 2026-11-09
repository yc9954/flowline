"""Read the pricing sheet (.ods) — Item / Amount columns and a Total row.

Reads the file bytes with pandas (odf engine) so the GUI is never involved.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import pandas as pd


@dataclass
class Sheet:
    items: list[tuple[str, int]] = field(default_factory=list)
    total: int | None = None

    @property
    def sum_items(self) -> int:
        return sum(a for _, a in self.items)

    def consistent(self) -> bool:
        return self.total is not None and self.total == self.sum_items


def parse_amount(v) -> int | None:
    """'$2,600' / 2600.0 / '2 600' → 2600; None when not a number."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if v != v:  # NaN
            return None
        return int(round(v))
    s = str(v).strip()
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in ("-", "."):
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def read_sheet_bytes(data: bytes, sheet_name: str | int = 0) -> Sheet:
    df = pd.read_excel(io.BytesIO(data), engine="odf", sheet_name=sheet_name, header=None)
    return parse_frame(df)


def read_sheet(path: str, sheet_name: str | int = 0) -> Sheet:
    with open(path, "rb") as f:
        return read_sheet_bytes(f.read(), sheet_name)


def parse_frame(df: pd.DataFrame) -> Sheet:
    df = df.dropna(how="all").reset_index(drop=True)
    if df.shape[1] < 2:
        raise ValueError("expected at least two columns (Item, Amount)")
    # Find the header row with Item / Amount (case-insensitive); default to row 0.
    header_idx = 0
    item_col, amt_col = 0, 1
    for i in range(min(5, len(df))):
        cells = [str(c).strip().lower() for c in df.iloc[i].tolist()]
        if "item" in cells and "amount" in cells:
            header_idx, item_col, amt_col = i, cells.index("item"), cells.index("amount")
            break
    else:
        raise ValueError("expected columns Item and Amount")
    sheet = Sheet()
    for i in range(header_idx + 1, len(df)):
        label = df.iat[i, item_col]
        amount = parse_amount(df.iat[i, amt_col])
        if label is None or (isinstance(label, float) and label != label):
            continue
        label = str(label).strip()
        if not label:
            continue
        if label.lower().startswith("total"):
            sheet.total = amount
            break
        if amount is not None:
            sheet.items.append((label, amount))
    if sheet.total is None:
        raise ValueError("expected a Total row")
    return sheet


def fmt_money(n: int) -> str:
    return f"${n:,}"
