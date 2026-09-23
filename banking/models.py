import secrets
import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Round
from django.utils import timezone

from .validators import normalize_phone


def account_number():
    return "PF" + secrets.token_hex(6).upper()


def loan_number():
    return "LN" + secrets.token_hex(6).upper()


class Timestamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Customer(Timestamped):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    full_name = models.CharField(max_length=150)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=13, unique=True)
    national_id = models.CharField(max_length=20, unique=True)

    def clean(self):
        self.phone_number = normalize_phone(self.phone_number)
        self.email = self.email.strip().lower()
        self.full_name = self.full_name.strip()
        self.national_id = self.national_id.strip().upper()

    def __str__(self):
        return self.full_name


class BankAccount(Timestamped):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        DORMANT = "DORMANT", "Dormant"
        CLOSED = "CLOSED", "Closed"

    class Type(models.TextChoices):
        SAVINGS = "SAVINGS", "Savings"
        CURRENT = "CURRENT", "Current"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="accounts")
    account_number = models.CharField(
        max_length=14, default=account_number, unique=True, editable=False
    )
    account_type = models.CharField(max_length=10, choices=Type, default=Type.SAVINGS)
    currency = models.CharField(max_length=3, default="KES", editable=False)
    balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("0.00"), validators=[MinValueValidator(0)]
    )
    status = models.CharField(max_length=8, choices=Status, default=Status.ACTIVE)
    last_activity_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        permissions = [
            ("operate_accounts", "Operate accounts as teller"),
            ("manage_accounts", "Manage dormancy, closure and loans"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(balance__gte=0), name="account_nonnegative"),
            models.CheckConstraint(condition=Q(currency="KES"), name="account_kes_only"),
            models.CheckConstraint(
                condition=Q(status__in=["ACTIVE", "DORMANT", "CLOSED"]), name="account_valid_status"
            ),
            models.CheckConstraint(
                condition=Q(account_type__in=["SAVINGS", "CURRENT"]), name="account_valid_type"
            ),
        ]

    @property
    def masked_number(self):
        return "•••• " + self.account_number[-4:]

    def __str__(self):
        return f"{self.customer} · {self.account_number}"


class ImmutableLedgerQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Ledger entries are immutable.")

    def delete(self):
        raise ValidationError("Ledger entries are immutable.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Ledger entries are immutable.")


class TransactionEntry(models.Model):
    class Type(models.TextChoices):
        OPENING = "OPENING", "Account opened"
        DEPOSIT = "DEPOSIT", "Deposit"
        WITHDRAWAL = "WITHDRAWAL", "Withdrawal"
        TRANSFER_IN = "TRANSFER_IN", "Transfer received"
        TRANSFER_OUT = "TRANSFER_OUT", "Transfer sent"
        LOAN_DISBURSEMENT = "LOAN_DISBURSEMENT", "Loan disbursed"
        ACCOUNT_CLOSURE = "ACCOUNT_CLOSURE", "Account closed"

    reference = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    transaction_type = models.CharField(max_length=20, choices=Type, db_index=True)
    account = models.ForeignKey(BankAccount, on_delete=models.PROTECT, related_name="entries")
    related_account = models.ForeignKey(
        BankAccount, on_delete=models.PROTECT, null=True, blank=True, related_name="related_entries"
    )
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    balance_before = models.DecimalField(max_digits=14, decimal_places=2)
    balance_after = models.DecimalField(max_digits=14, decimal_places=2)
    description = models.CharField(max_length=240, blank=True)
    transfer_group_reference = models.UUIDField(null=True, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    objects = ImmutableLedgerQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-pk"]
        indexes = [models.Index(fields=["account", "created_at"])]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(
                        transaction_type__in=["OPENING", "ACCOUNT_CLOSURE"],
                        amount=0,
                        balance_before=0,
                        balance_after=0,
                    )
                    | Q(
                        transaction_type__in=[
                            "DEPOSIT",
                            "WITHDRAWAL",
                            "TRANSFER_IN",
                            "TRANSFER_OUT",
                            "LOAN_DISBURSEMENT",
                        ],
                        amount__gt=0,
                    )
                ),
                name="ledger_valid_amount",
            ),
            models.CheckConstraint(
                condition=Q(balance_before__gte=0, balance_after__gte=0), name="ledger_nonnegative"
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        transaction_type__in=["OPENING", "ACCOUNT_CLOSURE"],
                        balance_after=F("balance_before"),
                    )
                    | Q(
                        transaction_type__in=["DEPOSIT", "TRANSFER_IN", "LOAN_DISBURSEMENT"],
                        balance_after=Round(F("balance_before") + F("amount"), 2),
                    )
                    | Q(
                        transaction_type__in=["WITHDRAWAL", "TRANSFER_OUT"],
                        balance_after=Round(F("balance_before") - F("amount"), 2),
                    )
                ),
                name="ledger_balances_match",
            ),
        ]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Ledger entries are immutable.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Ledger entries are immutable.")

    def __str__(self):
        return str(self.reference)


class LoanAccount(Timestamped):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        DISBURSED = "DISBURSED", "Disbursed"
        REPAID = "REPAID", "Repaid"
        CANCELLED = "CANCELLED", "Cancelled"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    bank_account = models.OneToOneField(BankAccount, on_delete=models.PROTECT, related_name="loan")
    loan_number = models.CharField(max_length=14, default=loan_number, unique=True, editable=False)
    principal_amount = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("10000.00")
    )
    outstanding_balance = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal("10000.00")
    )
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=10, choices=Status, default=Status.PENDING)
    disbursed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(principal_amount=10000), name="loan_fixed_principal"
            ),
            models.CheckConstraint(
                condition=Q(outstanding_balance__gte=0, outstanding_balance__lte=10000),
                name="loan_outstanding_range",
            ),
        ]

    def __str__(self):
        return self.loan_number
