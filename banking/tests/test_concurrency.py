from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import OperationalError, close_old_connections

from banking import services
from banking.models import TransactionEntry


@pytest.mark.django_db(transaction=True)
def test_concurrent_withdrawals_never_overdraw(account_factory):
    account = account_factory()
    services.deposit(account.public_id, "100.00")
    ready = Barrier(2)

    def withdraw():
        close_old_connections()
        ready.wait(timeout=10)
        try:
            services.withdraw(account.public_id, "75.00")
            return "completed"
        except (ValidationError, OperationalError):
            # Shared in-memory SQLite can reject a competing writer immediately.
            return "rejected"
        finally:
            close_old_connections()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: withdraw(), range(2)))
    account.refresh_from_db()
    assert outcomes.count("completed") == 1
    assert account.balance == 25
    assert TransactionEntry.objects.filter(transaction_type="WITHDRAWAL").count() == 1
