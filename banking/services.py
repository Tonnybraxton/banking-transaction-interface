from decimal import Decimal
from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import BankAccount, Customer, LoanAccount, TransactionEntry
from .validators import MAX_BALANCE, validate_amount


def _locked(public_id):
    return BankAccount.objects.select_for_update().get(public_id=public_id)


def _active(account):
    if account.status != BankAccount.Status.ACTIVE:
        raise ValidationError("This operation requires an active account.")


def _entry(account, kind, amount, before, **kwargs):
    return TransactionEntry.objects.create(
        account=account,
        transaction_type=kind,
        amount=amount,
        balance_before=before,
        balance_after=account.balance,
        **kwargs,
    )


def _move(account, delta, kind, **kwargs):
    before = account.balance
    after = before + delta
    if after < 0:
        raise ValidationError("Insufficient funds. Overdrafts are not allowed.")
    if after > MAX_BALANCE:
        raise ValidationError("This would exceed the account balance limit.")
    account.balance = after
    account.last_activity_at = timezone.now()
    account.save(update_fields=["balance", "last_activity_at", "updated_at"])
    return _entry(account, kind, abs(delta), before, **kwargs)


@transaction.atomic
def create_account(*, account_type, customer=None, **customer_data):
    if customer is None:
        customer = Customer(**customer_data)
        customer.full_clean()
        customer.save()
    account = BankAccount(customer=customer, account_type=account_type)
    account.full_clean()
    account.save()
    _entry(
        account,
        TransactionEntry.Type.OPENING,
        Decimal("0.00"),
        Decimal("0.00"),
        description="Account opened",
    )
    return account


@transaction.atomic
def deposit(public_id, amount, description=""):
    amount = validate_amount(amount)
    account = _locked(public_id)
    _active(account)
    return _move(account, amount, TransactionEntry.Type.DEPOSIT, description=description)


@transaction.atomic
def withdraw(public_id, amount, description=""):
    amount = validate_amount(amount)
    account = _locked(public_id)
    _active(account)
    return _move(account, -amount, TransactionEntry.Type.WITHDRAWAL, description=description)


@transaction.atomic
def transfer(source_id, destination_id, amount, description=""):
    amount = validate_amount(amount)
    accounts = list(
        BankAccount.objects.select_for_update()
        .filter(public_id__in=[source_id, destination_id])
        .order_by("pk")
    )
    if len(accounts) != 2:
        raise ValidationError("Choose two different, existing accounts.")
    source = next(a for a in accounts if str(a.public_id) == str(source_id))
    destination = next(a for a in accounts if a.pk != source.pk)
    _active(source)
    _active(destination)
    group = uuid4()
    outgoing = _move(
        source,
        -amount,
        TransactionEntry.Type.TRANSFER_OUT,
        related_account=destination,
        transfer_group_reference=group,
        description=description,
    )
    _move(
        destination,
        amount,
        TransactionEntry.Type.TRANSFER_IN,
        related_account=source,
        transfer_group_reference=group,
        description=description,
    )
    return outgoing


@transaction.atomic
def mark_dormant(public_id):
    account = _locked(public_id)
    _active(account)
    if (
        account.balance != 0
        or LoanAccount.objects.filter(bank_account=account, outstanding_balance__gt=0).exists()
    ):
        raise ValidationError("Dormancy requires a zero balance and no outstanding loan.")
    account.status = BankAccount.Status.DORMANT
    account.save(update_fields=["status", "updated_at"])
    return account


@transaction.atomic
def close_account(public_id):
    account = _locked(public_id)
    if account.status != BankAccount.Status.DORMANT:
        raise ValidationError("Only dormant accounts can be closed.")
    if account.balance != 0:
        raise ValidationError("The account balance must be KES 0.00.")
    if LoanAccount.objects.filter(bank_account=account, outstanding_balance__gt=0).exists():
        raise ValidationError("An outstanding loan prevents closure.")
    account.status = BankAccount.Status.CLOSED
    account.closed_at = timezone.now()
    account.save(update_fields=["status", "closed_at", "updated_at"])
    return _entry(
        account,
        TransactionEntry.Type.ACCOUNT_CLOSURE,
        Decimal("0.00"),
        account.balance,
        description="Dormant account closed; records retained for audit",
    )


@transaction.atomic
def disburse_loan(public_id):
    account = _locked(public_id)
    _active(account)
    if LoanAccount.objects.filter(bank_account=account).exists():
        raise ValidationError("This account has already received its one-time demo loan.")
    loan = LoanAccount.objects.create(bank_account=account)
    entry = _move(
        account,
        Decimal("10000.00"),
        TransactionEntry.Type.LOAN_DISBURSEMENT,
        description=f"One-time demo loan {loan.loan_number}",
    )
    loan.status = LoanAccount.Status.DISBURSED
    loan.disbursed_at = timezone.now()
    loan.save(update_fields=["status", "disbursed_at", "updated_at"])
    return entry
