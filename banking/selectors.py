from datetime import timedelta
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from .models import BankAccount, LoanAccount, TransactionEntry


def account_list(query="", status=""):
    accounts = BankAccount.objects.select_related("customer").order_by("-created_at")
    if status in BankAccount.Status.values:
        accounts = accounts.filter(status=status)
    else:
        accounts = accounts.exclude(status="CLOSED")
    if query:
        accounts = accounts.filter(
            Q(customer__full_name__icontains=query)
            | Q(account_number__icontains=query)
            | Q(customer__email__icontains=query)
        )
    return accounts


def ledger_entries(filters=None):
    entries = TransactionEntry.objects.select_related("account__customer", "related_account")
    for key, lookup in [
        ("account", "account"),
        ("type", "transaction_type"),
        ("start", "created_at__date__gte"),
        ("end", "created_at__date__lte"),
    ]:
        if filters and filters.get(key):
            entries = entries.filter(**{lookup: filters[key]})
    return entries


def dashboard_stats():
    accounts = BankAccount.objects.exclude(status="CLOSED")
    return {
        "total": accounts.count(),
        "active": accounts.filter(status="ACTIVE").count(),
        "dormant": accounts.filter(status="DORMANT").count(),
        "balance": accounts.aggregate(total=Sum("balance"))["total"] or Decimal("0.00"),
        "loans": LoanAccount.objects.filter(status="DISBURSED").count(),
        "recent": TransactionEntry.objects.filter(
            created_at__gte=timezone.now() - timedelta(days=30)
        ).count(),
    }
