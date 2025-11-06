import re
import threading
from dataclasses import FrozenInstanceError
from datetime import timezone
from decimal import Decimal

import pytest

from output/backend.accounts import (
    AccountService,
    ValidationError as AccountValidationError,
    AccountNotFoundError,
)
from output/backend.transactions import (
    TransactionLedger,
    Transaction,
    TransactionValidationError,
)


UUID4_HEX_RE = re.compile(r"[0-9a-f]{32}")


def is_uuid4_hex(s: str) -> bool:
    return bool(UUID4_HEX_RE.fullmatch(s))


def test_record_deposit_and_withdrawal_happy_path_and_immutability():
    ledger = TransactionLedger()

    # Deposit with trimming and quantization (100.005 -> 100.01)
    t_dep = ledger.record_deposit("  acc1  ", "100.005")
    assert isinstance(t_dep, Transaction)
    assert is_uuid4_hex(t_dep.id)
    assert t_dep.timestamp.tzinfo == timezone.utc
    assert t_dep.account_id == "acc1"
    assert t_dep.kind == "DEPOSIT"
    assert t_dep.amount == Decimal("100.01")
    assert t_dep.symbol is None and t_dep.quantity is None and t_dep.price is None and t_dep.total is None

    # Withdrawal with integer amount -> negative cash outflow
    t_wdr = ledger.record_withdrawal("acc1", 2)
    assert t_wdr.kind == "WITHDRAWAL"
    assert t_wdr.amount == Decimal("-2.00")
    assert t_wdr.symbol is None and t_wdr.quantity is None and t_wdr.price is None and t_wdr.total is None

    # Transaction dataclass is immutable
    with pytest.raises(FrozenInstanceError):
        t_dep.amount = Decimal("0")  # type: ignore[misc]


def test_record_buy_and_sell_fields_and_quantization():
    ledger = TransactionLedger()

    # Buy: symbol normalization, quantity/price quantization, total and negative amount
    t_buy = ledger.record_buy("acc2", "  eth  ", quantity="0.123456789", price="100.005")
    assert isinstance(t_buy, Transaction)
    assert is_uuid4_hex(t_buy.id)
    assert t_buy.timestamp.tzinfo == timezone.utc
    assert t_buy.account_id == "acc2"
    assert t_buy.kind == "BUY"
    assert t_buy.symbol == "ETH"
    assert t_buy.quantity == Decimal("0.12345679")
    assert t_buy.price == Decimal("100.01")
    assert t_buy.total == Decimal("12.35")
    assert t_buy.amount == Decimal("-12.35")

    # Sell: positive amount, symbol preserved uppercase; use small values that still quantize > 0
    t_sell = ledger.record_sell(" acc2 ", "ETH", quantity="0.01", price="0.5")
    assert t_sell.account_id == "acc2"
    assert t_sell.kind == "SELL"
    assert t_sell.symbol == "ETH"
    assert t_sell.quantity == Decimal("0.01")
    assert t_sell.price == Decimal("0.50")
    assert t_sell.total == Decimal("0.01")
    assert t_sell.amount == Decimal("0.01")
    assert t_sell.timestamp.tzinfo == timezone.utc


def test_invalid_inputs_validation_errors_for_id_symbol_amount_quantity_price():
    ledger = TransactionLedger()

    # account_id validation
    with pytest.raises(TransactionValidationError):
        ledger.record_deposit(123, 1)  # type: ignore[arg-type]
    with pytest.raises(TransactionValidationError):
        ledger.record_deposit("   ", 1)

    # symbol validation
    with pytest.raises(TransactionValidationError):
        ledger.record_buy("a", 123, 1, 1)  # type: ignore[arg-type]
    with pytest.raises(TransactionValidationError):
        ledger.record_buy("a", "   ", 1, 1)

    # Amount must be > 0 after quantization
    with pytest.raises(TransactionValidationError) as e1:
        ledger.record_deposit("a", 0)
    assert "amount must be > 0" in str(e1.value)

    with pytest.raises(TransactionValidationError) as e2:
        ledger.record_withdrawal("a", "0.004")  # quantizes to 0.00
    assert "amount must be > 0" in str(e2.value)

    # Quantity and price must be > 0 after quantization
    with pytest.raises(TransactionValidationError) as eq:
        ledger.record_buy("a", "ABC", quantity="0.000000004", price=1)
    assert "quantity must be > 0" in str(eq.value)

    with pytest.raises(TransactionValidationError) as ep:
        ledger.record_buy("a", "ABC", quantity=1, price="0.004")
    assert "price must be > 0" in str(ep.value)

    # Non-finite and non-numeric values
    with pytest.raises(TransactionValidationError) as efin:
        ledger.record_deposit("a", "NaN")
    assert "value must be a finite number" in str(efin.value)

    with pytest.raises(TransactionValidationError) as einv:
        ledger.record_deposit("a", "abc")
    assert "value is not a valid number" in str(einv.value)

    # Invalid kind filter
    with pytest.raises(TransactionValidationError):
        ledger.list_transactions(kind="DIVIDEND")

    # Invalid kind or symbol types in filters
    with pytest.raises(TransactionValidationError):
        ledger.list_transactions(kind=123)  # type: ignore[arg-type]
    with pytest.raises(TransactionValidationError):
        ledger.list_transactions(symbol=123)  # type: ignore[arg-type]


def test_list_transactions_filters_by_account_kind_and_symbol_and_convenience_method():
    ledger = TransactionLedger()
    # Populate transactions
    t1 = ledger.record_deposit("a1", 10)
    t2 = ledger.record_withdrawal("a1", 2)
    t3 = ledger.record_buy("a1", "BTC", 1, 5)
    t4 = ledger.record_sell("a1", "ETH", 2, 3)
    t5 = ledger.record_buy("a2", "ETH", 1, 1)
    t6 = ledger.record_deposit("a2", 7)

    all_txns = ledger.list_transactions()
    assert {t.id for t in all_txns} == {t1.id, t2.id, t3.id, t4.id, t5.id, t6.id}

    # Filter by kind (case-insensitive)
    a1_deposits = ledger.list_transactions(account_id="a1", kind="deposit")
    assert [t.kind for t in a1_deposits] == ["DEPOSIT"]
    assert a1_deposits[0].id == t1.id

    # Filter by symbol (case-insensitive); only BUY/SELL have symbols
    eth_txns = ledger.list_transactions(symbol="eth")
    assert {t.id for t in eth_txns} == {t4.id, t5.id}

    # Combined filters
    a1_buys = ledger.list_transactions(account_id="  a1  ", kind="BUY")
    assert [t.id for t in a1_buys] == [t3.id]

    # Convenience wrapper returns same as list_transactions with account_id
    assert ledger.get_account_transactions("a1", kind="BUY") == a1_buys


def test_constructor_invalid_parameters_raise():
    with pytest.raises(TransactionValidationError):
        TransactionLedger(currency_precision=-1)
    with pytest.raises(TransactionValidationError):
        TransactionLedger(asset_precision=-1)
    with pytest.raises(TransactionValidationError):
        TransactionLedger(currency_precision=1.5)  # type: ignore[arg-type]
    with pytest.raises(TransactionValidationError):
        TransactionLedger(asset_precision="2")  # type: ignore[arg-type]


def test_account_validation_when_account_service_is_provided_and_filter_validates():
    acct = AccountService()
    acc_id = acct.create_account("accv", initial_balance=0)
    ledger = TransactionLedger(account_service=acct)

    # Valid account works
    dep = ledger.record_deposit(acc_id, 1)
    assert dep.account_id == "accv"

    # Non-existent account should raise AccountNotFoundError (delegated)
    with pytest.raises(AccountNotFoundError):
        ledger.record_deposit("missing", 1)

    with pytest.raises(AccountNotFoundError):
        ledger.list_transactions(account_id="missing")

    # Invalid account id format triggers TransactionValidationError before delegation
    with pytest.raises(TransactionValidationError):
        ledger.record_deposit("   ", 1)
    with pytest.raises(TransactionValidationError):
        ledger.list_transactions(account_id="   ")

    # Without AccountService, list_transactions should not validate existence
    ledger_noacct = TransactionLedger()
    assert ledger_noacct.list_transactions(account_id="missing") == []


def test_precision_configuration_and_rounding_behavior():
    # Custom precisions: asset=2, currency=0
    ledger = TransactionLedger(currency_precision=0, asset_precision=2)

    # Deposit 0.4 -> quantizes to 0 -> invalid; 0.5 -> rounds to 1
    with pytest.raises(TransactionValidationError):
        ledger.record_deposit("p", 0.4)
    dep = ledger.record_deposit("p", 0.5)
    assert dep.amount == Decimal("1")

    # Buy: quantity -> 1.23, price -> 6, total -> 7, amount -7
    buy = ledger.record_buy("p", "XRP", quantity="1.234", price="5.5")
    assert buy.quantity == Decimal("1.23")
    assert buy.price == Decimal("6")
    assert buy.total == Decimal("7")
    assert buy.amount == Decimal("-7")


def test_thread_safety_concurrent_records_and_counts_and_amounts():
    ledger = TransactionLedger()
    acc = "thread"
    qty = Decimal("0.01")
    price = Decimal("1.00")  # per-trade total 0.01 -> amount -0.01
    per_thread = 200
    n_threads = 5

    def worker():
        for _ in range(per_thread):
            ledger.record_buy(acc, "XYZ", quantity=qty, price=price)

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total_trades = per_thread * n_threads
    acc_buys = ledger.list_transactions(account_id=acc, kind="BUY")
    assert len(acc_buys) == total_trades

    total_amount = sum((t.amount for t in acc_buys), Decimal(0))
    expected_amount = Decimal("-0.01") * total_trades
    assert total_amount == expected_amount


def test_list_transactions_symbol_filter_normalization_and_kind_validation():
    ledger = TransactionLedger()
    ledger.record_buy("a", " eth ", 1, 1)
    ledger.record_sell("a", "ETH", 1, 1)

    # symbol filter normalizes whitespace and case
    eth_filtered = ledger.list_transactions(symbol="  eTh  ")
    assert len(eth_filtered) == 2
    assert {t.kind for t in eth_filtered} == {"BUY", "SELL"}

    # invalid kind values
    with pytest.raises(TransactionValidationError):
        ledger.list_transactions(kind="hold")