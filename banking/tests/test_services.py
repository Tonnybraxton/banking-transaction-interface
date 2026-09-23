from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from banking import services
from banking.models import BankAccount, Customer, LoanAccount, TransactionEntry
from banking.validators import MAX_BALANCE, normalize_phone, validate_amount

pytestmark = pytest.mark.django_db


def test_account_creation(account):
    assert account.balance == Decimal("0.00")
    assert account.status == "ACTIVE"
    assert account.account_number.startswith("PF")
    assert len(account.account_number) == 14
    assert account.public_id
    assert account.customer.phone_number == "+254712340001"
    opening = account.entries.get()
    assert opening.transaction_type == "OPENING"
    assert opening.amount == opening.balance_before == opening.balance_after == 0
    assert str(account.customer) in str(account)
    assert str(opening) == str(opening.reference)
    assert account.masked_number.endswith(account.account_number[-4:])


def test_existing_customer_and_unique_numbers(account, account_factory):
    other = services.create_account(account_type="CURRENT", customer=account.customer)
    assert Customer.objects.count() == 1
    assert other.account_number != account.account_number
    assert other.public_id != account.public_id


def test_deposit(account):
    entry = services.deposit(account.public_id, "25000.00", "First deposit")
    account.refresh_from_db()
    assert account.balance == Decimal("25000.00")
    assert (entry.balance_before, entry.balance_after, entry.amount) == (0, 25000, 25000)
    assert account.last_activity_at >= account.created_at
    assert entry.description == "First deposit"


def test_fractional_cents_are_exact(account, account_factory):
    other = account_factory()
    services.deposit(account.public_id, "0.10")
    services.deposit(account.public_id, "0.20")
    services.withdraw(account.public_id, "0.10")
    services.transfer(account.public_id, other.public_id, "0.07")
    account.refresh_from_db()
    other.refresh_from_db()
    assert account.balance == Decimal("0.13")
    assert other.balance == Decimal("0.07")


def test_withdraw(account):
    services.deposit(account.public_id, "25000.00")
    entry = services.withdraw(account.public_id, "5000.00")
    account.refresh_from_db()
    assert account.balance == Decimal("20000.00")
    assert entry.transaction_type == "WITHDRAWAL"
    assert (entry.balance_before, entry.balance_after) == (25000, 20000)


def test_insufficient_funds_rollback(account):
    with pytest.raises(ValidationError, match="Insufficient"):
        services.withdraw(account.public_id, "1.00")
    account.refresh_from_db()
    assert account.balance == 0
    assert account.entries.count() == 1


def test_transfer(account, account_factory):
    other = account_factory()
    services.deposit(account.public_id, "20000.00")
    entry = services.transfer(account.public_id, other.public_id, "2500.00")
    account.refresh_from_db()
    other.refresh_from_db()
    assert (account.balance, other.balance) == (17500, 2500)
    pair = TransactionEntry.objects.filter(transfer_group_reference=entry.transfer_group_reference)
    assert pair.count() == 2
    assert set(pair.values_list("transaction_type", flat=True)) == {"TRANSFER_IN", "TRANSFER_OUT"}
    assert entry.related_account_id == other.pk
    assert pair.get(transaction_type="TRANSFER_IN").related_account_id == account.pk


def test_failed_transfer_rollback(account, account_factory):
    other = account_factory()
    services.deposit(account.public_id, "100.00")
    original = services._entry

    def fail_destination(account, kind, *args, **kwargs):
        if kind == "TRANSFER_IN":
            raise IntegrityError("Simulated ledger write failure")
        return original(account, kind, *args, **kwargs)

    with patch("banking.services._entry", side_effect=fail_destination):
        with pytest.raises(IntegrityError):
            services.transfer(account.public_id, other.public_id, "25.00")
    account.refresh_from_db()
    other.refresh_from_db()
    assert (account.balance, other.balance) == (100, 0)
    assert not TransactionEntry.objects.filter(transaction_type__startswith="TRANSFER").exists()


@pytest.mark.parametrize("target", ["self", "missing"])
def test_bad_transfer_target(account, target):
    with pytest.raises(ValidationError):
        services.transfer(
            account.public_id, account.public_id if target == "self" else uuid4(), "1.00"
        )


@pytest.mark.parametrize(
    "value",
    ["0", "-1", "0.001", "10000000.01", "NaN", "Infinity", "-Infinity", "text", 1.5, True, None],
)
def test_invalid_amounts(account, value):
    with pytest.raises(ValidationError):
        services.deposit(account.public_id, value)
    assert account.entries.count() == 1


def test_amount_boundary():
    assert validate_amount("10000000.00") == Decimal("10000000.00")


@pytest.mark.parametrize("status", ["DORMANT", "CLOSED"])
@pytest.mark.parametrize(
    "operation", ["deposit", "withdraw", "transfer_source", "transfer_destination", "loan"]
)
def test_inactive_operations(account, account_factory, status, operation):
    other = account_factory()
    BankAccount.objects.filter(pk=account.pk).update(status=status)
    with pytest.raises(ValidationError):
        if operation == "transfer_source":
            services.transfer(account.public_id, other.public_id, "1.00")
        elif operation == "transfer_destination":
            services.transfer(other.public_id, account.public_id, "1.00")
        elif operation == "loan":
            services.disburse_loan(account.public_id)
        else:
            getattr(services, operation)(account.public_id, "1.00")
    assert TransactionEntry.objects.count() == 2


def test_dormant_closure(account):
    services.mark_dormant(account.public_id)
    entry = services.close_account(account.public_id)
    account.refresh_from_db()
    assert account.status == "CLOSED"
    assert account.closed_at is not None
    assert entry.transaction_type == "ACCOUNT_CLOSURE"
    assert entry.amount == 0
    assert Customer.objects.filter(pk=account.customer_id).exists()
    assert account.entries.count() == 2


@pytest.mark.parametrize("condition", ["active", "funded", "loan"])
def test_invalid_closure(account, condition):
    if condition == "funded":
        services.deposit(account.public_id, "1.00")
    if condition == "loan":
        LoanAccount.objects.create(bank_account=account)
    if condition != "active":
        BankAccount.objects.filter(pk=account.pk).update(status="DORMANT")
    with pytest.raises(ValidationError):
        services.close_account(account.public_id)
    assert not account.entries.filter(transaction_type="ACCOUNT_CLOSURE").exists()


@pytest.mark.parametrize("condition", ["funded", "loan", "already_dormant"])
def test_invalid_dormancy(account, condition):
    if condition == "funded":
        services.deposit(account.public_id, "1.00")
    elif condition == "loan":
        LoanAccount.objects.create(bank_account=account)
    else:
        services.mark_dormant(account.public_id)
    with pytest.raises(ValidationError):
        services.mark_dormant(account.public_id)


def test_loan_disbursement_once(account):
    services.deposit(account.public_id, "17500.00")
    entry = services.disburse_loan(account.public_id)
    account.refresh_from_db()
    assert account.balance == Decimal("27500.00")
    assert entry.amount == Decimal("10000.00")
    assert entry.balance_after - entry.balance_before == Decimal("10000.00")
    loan = account.loan
    assert loan.principal_amount == loan.outstanding_balance == Decimal("10000.00")
    assert loan.status == "DISBURSED" and loan.disbursed_at
    assert str(loan) == loan.loan_number
    with pytest.raises(ValidationError, match="already received"):
        services.disburse_loan(account.public_id)
    account.refresh_from_db()
    assert account.balance == 27500
    assert LoanAccount.objects.count() == 1
    assert account.entries.filter(transaction_type="LOAN_DISBURSEMENT").count() == 1


def test_loan_failure_rolls_back(account):
    with patch("banking.services._entry", side_effect=IntegrityError("Ledger failure")):
        with pytest.raises(IntegrityError):
            services.disburse_loan(account.public_id)
    account.refresh_from_db()
    assert account.balance == 0
    assert not LoanAccount.objects.exists()


def test_balance_capacity(account):
    BankAccount.objects.filter(pk=account.pk).update(balance=MAX_BALANCE)
    with pytest.raises(ValidationError, match="balance limit"):
        services.deposit(account.public_id, "0.01")


@pytest.mark.parametrize(
    "field,value",
    [("email", "C1@EXAMPLE.TEST"), ("phone_number", "+254712340001"), ("national_id", "TEST0001")],
)
def test_duplicate_customers(account, account_factory, field, value):
    with pytest.raises(ValidationError):
        account_factory(**{field: value})
    assert Customer.objects.count() == 1


@pytest.mark.parametrize("value", ["0712 345 678", "254712345678", "+254712345678"])
def test_phone_normalization(value):
    assert normalize_phone(value) == "+254712345678"


def test_invalid_phone():
    with pytest.raises(ValidationError):
        normalize_phone("123")


def test_database_constraints(account, account_factory):
    with pytest.raises(IntegrityError), transaction.atomic():
        BankAccount.objects.filter(pk=account.pk).update(balance=-1)
    with pytest.raises(IntegrityError), transaction.atomic():
        BankAccount.objects.create(customer=account.customer, account_number=account.account_number)
    loan = LoanAccount.objects.create(bank_account=account)
    with pytest.raises(IntegrityError), transaction.atomic():
        LoanAccount.objects.create(bank_account=account)
    other = account_factory()
    with pytest.raises(IntegrityError), transaction.atomic():
        LoanAccount.objects.create(bank_account=other, loan_number=loan.loan_number)


def test_ledger_immutable(account):
    entry = account.entries.get()
    for operation in [
        lambda: entry.save(),
        lambda: entry.delete(),
        lambda: account.entries.update(description="tamper"),
        lambda: account.entries.all().delete(),
        lambda: account.entries.bulk_update([entry], ["description"]),
    ]:
        with pytest.raises(ValidationError, match="immutable"):
            operation()
