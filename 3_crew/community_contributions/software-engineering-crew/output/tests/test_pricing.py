import pytest
from decimal import Decimal

from output/backend/pricing import PriceService, PricingError, SymbolNotSupportedError


def test_get_share_price_supported_symbols_case_insensitive_and_trimmed():
    svc = PriceService()

    # Exact symbols
    assert svc.get_share_price("AAPL") == Decimal("150.00")
    assert svc.get_share_price("TSLA") == Decimal("250.00")
    assert svc.get_share_price("GOOGL") == Decimal("2750.00")

    # Case-insensitive and whitespace trimming
    assert svc.get_share_price("  aapl  ") == Decimal("150.00")
    assert svc.get_share_price("tsla") == Decimal("250.00")
    assert svc.get_share_price("  GooGl ") == Decimal("2750.00")


def test_get_share_price_returns_decimal_with_two_decimal_places():
    svc = PriceService()
    for sym in ("AAPL", "TSLA", "GOOGL"):
        price = svc.get_share_price(sym)
        assert isinstance(price, Decimal)
        # Ensure two decimal places
        assert price.as_tuple().exponent == -2


def test_get_share_price_invalid_symbol_input_raises_pricing_error():
    svc = PriceService()

    with pytest.raises(PricingError) as e_type:
        svc.get_share_price(123)  # type: ignore[arg-type]
    assert "symbol must be a string" in str(e_type.value)

    with pytest.raises(PricingError) as e_empty:
        svc.get_share_price("   ")
    assert "symbol must be a non-empty string" in str(e_empty.value)


def test_get_share_price_unsupported_symbol_raises_symbol_not_supported_error():
    svc = PriceService()
    with pytest.raises(SymbolNotSupportedError) as e_unsup:
        svc.get_share_price("MSFT")
    # Error message includes normalized uppercase symbol
    assert "symbol 'MSFT' is not supported" in str(e_unsup.value)