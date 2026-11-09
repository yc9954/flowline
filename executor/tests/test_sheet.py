import os

import pandas as pd
import pytest

from sheet import Sheet, fmt_money, parse_amount, parse_frame, read_sheet

HERE = os.path.dirname(os.path.abspath(__file__))
ODS = os.path.join(os.path.dirname(HERE), "assets", "pricing-sheet.ods")


def test_parse_amount():
    assert parse_amount("$2,600") == 2600
    assert parse_amount(2600.0) == 2600
    assert parse_amount("540") == 540
    assert parse_amount("") is None
    assert parse_amount(None) is None
    assert parse_amount(float("nan")) is None


def test_parse_frame_synthetic():
    df = pd.DataFrame([["Item", "Amount"], ["A", 10], ["B", "$20"], ["Total", 30], ["ignored", 99]])
    s = parse_frame(df)
    assert s.items == [("A", 10), ("B", 20)]
    assert s.total == 30
    assert s.consistent()


def test_parse_frame_requires_total():
    with pytest.raises(ValueError):
        parse_frame(pd.DataFrame([["Item", "Amount"], ["A", 10]]))


@pytest.mark.skipif(not os.path.exists(ODS), reason="assets not built")
def test_read_real_sheet():
    s = read_sheet(ODS)
    assert s.items == [("Memberships, 120 seats", 2600), ("Lunchtime classes, 8 / mo", 1150), ("Onboarding week", 540)]
    assert s.total == 4290 and s.consistent()
    assert fmt_money(s.total) == "$4,290"
