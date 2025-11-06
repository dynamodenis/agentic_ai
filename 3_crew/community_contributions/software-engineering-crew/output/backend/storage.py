from __future__ import annotations

"""
storage.py

A self-contained in-memory repository that maintains data structures for
accounts, holdings, and transactions. It provides a simple, thread-safe layer
for storing and retrieving these records without enforcing business rules from
higher-level services.

This module is intentionally minimal and focuses on storage concerns only:
  - Accounts: id -> balance (Decimal)
  - Holdings: account_id -> symbol -> quantity (Decimal)
  - Transactions: append-only immutable records

Notes:
  - Input validation ensures basic types and normalization (IDs trimmed, symbols
    upper-cased, finite Decimal values).
  - No monetary rounding or domain validations are applied here; those belong
    to higher-level services. The store accepts provided Decimal-like values as-is.
  - Thread-safe via an internal re-entrant lock (RLock).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from threading import RLock
from typing import Dict, List, Optional, Union
from uuid import uuid4

__all__ = [
    "StorageError",
    "StorageValidationError",
    "RecordNotFoundError",
    "DuplicateRecordError",
    "AccountSnapshot",
    "TransactionRecord",
    "InMemoryStore",
]

NumberLike = Union[int, float, str, Decimal]


class StorageError(Exception):
    """Base exception for storage-related errors."""


class StorageValidationError(StorageError):
    """Raised when input validation fails for the storage layer."""


class RecordNotFoundError(StorageError):
    """Raised when a requested record does not exist in the store."""


class DuplicateRecordError(StorageError):
    """Raised when attempting to create a record that already exists."""


@dataclass(frozen=True)
class AccountSnapshot:
    """Immutable snapshot of an account record.

    Attributes:
        id: Account identifier.
        balance: Current balance stored for the account.
    """

    id: str
    balance: Decimal


@dataclass(frozen=True)
class TransactionRecord:
    """Immutable transaction record stored by the repository.

    Attributes:
        id: Unique transaction identifier (UUID4 hex).
        account_id: The account associated with the transaction.
        kind: One of "DEPOSIT", "WITHDRAWAL", "BUY", "SELL".
        timestamp: UTC timestamp when the transaction was recorded.
        amount: Cash flow amount. Positive for inflows (DEPOSIT, SELL),
                negative for outflows (WITHDRAWAL, BUY).
        symbol: Optional traded asset symbol (upper-cased) for BUY/SELL.
        quantity: Optional executed quantity for BUY/SELL.
        price: Optional executed price per unit for BUY/SELL.
        total: Optional total trade value for BUY/SELL.
    """

    id: str
    account_id: str
    kind: str
    timestamp: datetime
    amount: Decimal
    symbol: Optional[str] = None
    quantity: Optional[Decimal] = None
    price: Optional[Decimal] = None
    total: Optional[Decimal] = None


class InMemoryStore:
    """Thread-safe in-memory repository for accounts, holdings, and transactions.

    This class provides a minimal storage abstraction that higher-level services
    can use to persist and retrieve domain data without coupling to a specific
    storage technology.
    """

    def __init__(self) -> None:
        self._lock = RLock()
        self._accounts: Dict[str, Decimal] = {}
        self._holdings: Dict[str, Dict[str, Decimal]] = {}
        self._transactions: List[TransactionRecord] = []

    # -----------------------------
    # Account storage operations
    # -----------------------------

    def create_account(self, account_id: Optional[str] = None, initial_balance: NumberLike = 0) -> str:
        """Create a new account with an optional initial balance.

        Args:
            account_id: Optional explicit ID; if None, a UUID4 hex is generated.
            initial_balance: Initial balance (number-like), stored as Decimal.

        Returns:
            The created account ID.

        Raises:
            StorageValidationError: If account_id is invalid or initial_balance is not a finite number.
            DuplicateRecordError: If an account with the given ID already exists.
        """
        acc_id = self._normalize_id(account_id) if account_id is not None else uuid4().hex
        balance = self._coerce_decimal(initial_balance)

        with self._lock:
            if acc_id in self._accounts:
                raise DuplicateRecordError(f"account '{acc_id}' already exists")
            self._accounts[acc_id] = balance
        return acc_id

    def get_account(self, account_id: str) -> AccountSnapshot:
        """Retrieve an immutable snapshot of the account.

        Raises:
            StorageValidationError: If account_id is invalid.
            RecordNotFoundError: If the account does not exist.
        """
        acc_id = self._normalize_id(account_id)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            return AccountSnapshot(id=acc_id, balance=self._accounts[acc_id])

    def get_balance(self, account_id: str) -> Decimal:
        """Get the current balance for an account."""
        return self.get_account(account_id).balance

    def set_balance(self, account_id: str, new_balance: NumberLike) -> Decimal:
        """Set the account balance to a new value.

        Returns:
            The stored balance as Decimal.
        """
        acc_id = self._normalize_id(account_id)
        bal = self._coerce_decimal(new_balance)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            self._accounts[acc_id] = bal
            return bal

    def update_balance(self, account_id: str, delta: NumberLike) -> Decimal:
        """Add a delta to the account balance and return the new balance."""
        acc_id = self._normalize_id(account_id)
        d = self._coerce_decimal(delta)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            new_bal = self._accounts[acc_id] + d
            self._accounts[acc_id] = new_bal
            return new_bal

    def list_accounts(self) -> List[AccountSnapshot]:
        """List all accounts as immutable snapshots."""
        with self._lock:
            return [AccountSnapshot(id=k, balance=v) for k, v in self._accounts.items()]

    # -----------------------------
    # Holdings storage operations
    # -----------------------------

    def get_holdings(self, account_id: str) -> Dict[str, Decimal]:
        """Return a snapshot of holdings for the given account.

        Raises:
            StorageValidationError: If account_id is invalid.
            RecordNotFoundError: If the account does not exist.
        """
        acc_id = self._normalize_id(account_id)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            return dict(self._holdings.get(acc_id, {}))

    def get_position(self, account_id: str, symbol: str) -> Decimal:
        """Get the quantity held for a specific symbol; returns Decimal(0) if none."""
        acc_id = self._normalize_id(account_id)
        sym = self._normalize_symbol(symbol)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            return self._holdings.get(acc_id, {}).get(sym, Decimal(0))

    def set_position(self, account_id: str, symbol: str, quantity: NumberLike) -> Decimal:
        """Set the position quantity for a symbol, replacing any existing value.

        If the quantity is zero, the position is removed from the account holdings.

        Returns:
            The stored quantity as Decimal.
        """
        acc_id = self._normalize_id(account_id)
        sym = self._normalize_symbol(symbol)
        qty = self._coerce_decimal(quantity)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            acct_pos = self._holdings.setdefault(acc_id, {})
            if qty == Decimal(0):
                acct_pos.pop(sym, None)
                # clean empty map
                if not acct_pos:
                    self._holdings.pop(acc_id, None)
                return Decimal(0)
            acct_pos[sym] = qty
            return qty

    def adjust_position(self, account_id: str, symbol: str, delta: NumberLike) -> Decimal:
        """Adjust the position quantity for a symbol by a delta and return the new quantity."""
        acc_id = self._normalize_id(account_id)
        sym = self._normalize_symbol(symbol)
        d = self._coerce_decimal(delta)
        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            acct_pos = self._holdings.setdefault(acc_id, {})
            cur = acct_pos.get(sym, Decimal(0))
            new_qty = cur + d
            if new_qty == Decimal(0):
                acct_pos.pop(sym, None)
                if not acct_pos:
                    self._holdings.pop(acc_id, None)
                return Decimal(0)
            acct_pos[sym] = new_qty
            return new_qty

    # -----------------------------
    # Transaction storage operations
    # -----------------------------

    def add_transaction(
        self,
        *,
        account_id: str,
        kind: str,
        amount: NumberLike,
        symbol: Optional[str] = None,
        quantity: Optional[NumberLike] = None,
        price: Optional[NumberLike] = None,
        total: Optional[NumberLike] = None,
        timestamp: Optional[datetime] = None,
        txn_id: Optional[str] = None,
    ) -> str:
        """Append a new transaction record and return its ID.

        This method performs basic validation and normalization but does not apply
        any business rules (e.g., sign of amounts, sufficiency checks).
        """
        acc_id = self._normalize_id(account_id)
        k = self._normalize_kind(kind)
        amt = self._coerce_decimal(amount)
        sym: Optional[str] = None
        qty: Optional[Decimal] = None
        px: Optional[Decimal] = None
        ttl: Optional[Decimal] = None

        if symbol is not None:
            sym = self._normalize_symbol(symbol)
        if quantity is not None:
            qty = self._coerce_decimal(quantity)
        if price is not None:
            px = self._coerce_decimal(price)
        if total is not None:
            ttl = self._coerce_decimal(total)

        ts = timestamp if timestamp is not None else datetime.now(timezone.utc)
        if ts.tzinfo is None:
            # Ensure timezone-aware UTC timestamp
            ts = ts.replace(tzinfo=timezone.utc)

        tid = txn_id if txn_id is not None else uuid4().hex

        with self._lock:
            if acc_id not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_id}' not found")
            rec = TransactionRecord(
                id=tid,
                account_id=acc_id,
                kind=k,
                timestamp=ts,
                amount=amt,
                symbol=sym,
                quantity=qty,
                price=px,
                total=ttl,
            )
            self._transactions.append(rec)
            return tid

    def list_transactions(
        self,
        account_id: Optional[str] = None,
        *,
        kind: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[TransactionRecord]:
        """List transactions with optional filtering by account, kind, and symbol."""
        acc_norm: Optional[str] = None
        kind_norm: Optional[str] = None
        sym_norm: Optional[str] = None

        if account_id is not None:
            acc_norm = self._normalize_id(account_id)
        if kind is not None:
            kind_norm = self._normalize_kind(kind)
        if symbol is not None:
            sym_norm = self._normalize_symbol(symbol)

        with self._lock:
            # If account filter provided, ensure it exists for clearer semantics
            if acc_norm is not None and acc_norm not in self._accounts:
                raise RecordNotFoundError(f"account '{acc_norm}' not found")

            result = [
                t
                for t in self._transactions
                if (acc_norm is None or t.account_id == acc_norm)
                and (kind_norm is None or t.kind == kind_norm)
                and (sym_norm is None or t.symbol == sym_norm)
            ]
            return list(result)

    def get_account_transactions(
        self,
        account_id: str,
        *,
        kind: Optional[str] = None,
        symbol: Optional[str] = None,
    ) -> List[TransactionRecord]:
        """Convenience wrapper to list transactions for a single account."""
        return self.list_transactions(account_id=account_id, kind=kind, symbol=symbol)

    # -----------------------------
    # Internal helpers
    # -----------------------------

    def _normalize_id(self, account_id: str) -> str:
        if not isinstance(account_id, str):
            raise StorageValidationError("account_id must be a string")
        acc_id = account_id.strip()
        if not acc_id:
            raise StorageValidationError("account_id must be a non-empty string")
        return acc_id

    def _normalize_symbol(self, symbol: str) -> str:
        if not isinstance(symbol, str):
            raise StorageValidationError("symbol must be a string")
        sym = symbol.strip()
        if not sym:
            raise StorageValidationError("symbol must be a non-empty string")
        return sym.upper()

    def _normalize_kind(self, kind: str) -> str:
        if not isinstance(kind, str):
            raise StorageValidationError("kind must be a string")
        k = kind.strip().upper()
        if k not in {"DEPOSIT", "WITHDRAWAL", "BUY", "SELL"}:
            raise StorageValidationError("kind must be one of: DEPOSIT, WITHDRAWAL, BUY, SELL")
        return k

    def _coerce_decimal(self, value: NumberLike) -> Decimal:
        try:
            if isinstance(value, Decimal):
                d = value
            elif isinstance(value, int):
                d = Decimal(value)
            elif isinstance(value, float):
                d = Decimal(str(value))
            elif isinstance(value, str):
                d = Decimal(value.strip())
            else:
                raise StorageValidationError(
                    "value must be a number-like type (int, float, str, Decimal)"
                )
        except (InvalidOperation, ValueError) as exc:
            raise StorageValidationError("value is not a valid number") from exc

        if not d.is_finite():
            raise StorageValidationError("value must be a finite number")
        return d