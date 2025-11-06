from __future__ import annotations

from decimal import Decimal
from typing import Dict

__all__ = [
    "PricingError",
    "SymbolNotSupportedError",
    "PriceService",
]


class PricingError(Exception):
    """Base exception for pricing-related errors."""


class SymbolNotSupportedError(PricingError):
    """Raised when a requested symbol does not have a configured test price."""


class PriceService:
    """Static price provider for a small set of test equities.

    This service exposes a simple get_share_price(symbol) API that returns a fixed
    Decimal price for supported symbols. It is intended for use in tests or
    deterministic environments where external price feeds are not desirable.

    Supported symbols and their fixed prices (USD):
      - AAPL: 150.00
      - TSLA: 250.00
      - GOOGL: 2750.00

    Notes:
      - Symbols are case-insensitive and normalized to upper-case.
      - Prices are returned as Decimal with two fractional digits.
    """

    # Fixed test price map
    _PRICES: Dict[str, Decimal] = {
        "AAPL": Decimal("150.00"),
        "TSLA": Decimal("250.00"),
        "GOOGL": Decimal("2750.00"),
    }

    def get_share_price(self, symbol: str) -> Decimal:
        """Return the fixed test price for the given equity symbol.

        Args:
            symbol: The equity ticker symbol (e.g., "AAPL", "TSLA", "GOOGL").

        Returns:
            The price as a Decimal with two decimal places.

        Raises:
            PricingError: If symbol is not a string or empty after trimming.
            SymbolNotSupportedError: If the symbol is not supported by this service.
        """
        if not isinstance(symbol, str):
            raise PricingError("symbol must be a string")
        sym = symbol.strip()
        if not sym:
            raise PricingError("symbol must be a non-empty string")
        sym = sym.upper()

        try:
            return self._PRICES[sym]
        except KeyError as exc:
            raise SymbolNotSupportedError(f"symbol '{sym}' is not supported") from exc