import pytest

from harnessy.cost import PRICES, PRICES_CHECKED, Price, cost_usd, price_for
from harnessy.types import Usage


def test_the_price_table_is_given():
    assert PRICES["claude-opus-5"] == Price(5.0, 25.0) and PRICES["gpt-5.5"] == Price(5.0, 30.0)
    assert PRICES_CHECKED == "2026-09-28"


def test_price_for_exact_and_dated_names():
    prices = {"gpt-5.5": Price(5, 30), "gpt-5": Price(1, 2), "claude-opus-5": Price(5, 25)}
    assert price_for("gpt-5.5", prices) == Price(5, 30)
    assert price_for("gpt-5.5-2026-04-23", prices) == Price(5, 30)
    assert price_for("claude-opus-5-20260915", prices) == Price(5, 25)
    assert price_for("gpt-5.55", prices) is None
    assert price_for("gpt-5.5-pro", prices) is None  # a different model, not a dated id
    assert price_for("gpt-5.5-mini", prices) is None
    assert price_for("claude-opus-5-1", prices) is None
    assert price_for("llama3", prices) is None


def test_cost_usd():
    assert cost_usd(Usage(1_000_000, 0), Price(5, 25)) == 5.0
    assert cost_usd(Usage(2_000, 400), Price(5, 25)) == pytest.approx(0.02)
