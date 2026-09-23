from io import StringIO
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib import admin
from django.core.management import call_command
from django.db import IntegrityError, OperationalError
from django.test import Client, override_settings
from django.urls import reverse

from banking import services
from banking.models import BankAccount, Customer, LoanAccount, TransactionEntry

pytestmark = pytest.mark.django_db


def url(name, account=None):
    return reverse(f"banking:{name}", args=[account.public_id] if account else [])


def test_evaluator_journey(manager_client):
    def create(index):
        response = manager_client.post(
            url("create"),
            {
                "full_name": f"Evaluator {index}",
                "email": f"e{index}@example.test",
                "phone_number": f"071100000{index}",
                "national_id": f"EVAL{index:04}",
                "account_type": "SAVINGS",
            },
        )
        assert response.status_code == 302
        return BankAccount.objects.get(customer__email=f"e{index}@example.test")

    first = create(1)
    assert (
        manager_client.post(url("deposit", first), {"amount": "25000.00"}, follow=True).status_code
        == 200
    )
    assert (
        manager_client.post(url("withdraw", first), {"amount": "5000.00"}, follow=True).status_code
        == 200
    )
    first.refresh_from_db()
    assert first.balance == 20000
    second = create(2)
    response = manager_client.post(
        url("transfer", first), {"amount": "2500.00", "destination": second.public_id}, follow=True
    )
    assert b"Both sides of the transfer" in response.content
    assert TransactionEntry.objects.filter(transaction_type__startswith="TRANSFER").count() == 2
    first.refresh_from_db()
    before = first.balance
    response = manager_client.post(url("loan", first), {"confirm": "on"}, follow=True)
    assert response.status_code == 200
    first.refresh_from_db()
    assert first.balance - before == 10000
    assert first.balance == 27500
    assert first.loan.status == "DISBURSED"
    response = manager_client.post(url("loan", first), {"confirm": "on"})
    assert b"already received" in response.content
    first.refresh_from_db()
    assert first.balance == 27500
    second.refresh_from_db()
    assert second.balance == 2500
    third = create(3)
    assert manager_client.post(url("dormant", third), {"confirm": "on"}).status_code == 302
    assert manager_client.post(url("close", third), {"confirm": "on"}).status_code == 302
    third.refresh_from_db()
    assert third.status == "CLOSED"
    assert third.entries.filter(transaction_type="ACCOUNT_CLOSURE").exists()
    assert manager_client.get(url("ledger")).status_code == 200


@pytest.mark.parametrize("name", ["dashboard", "accounts", "create", "ledger"])
def test_primary_pages(manager_client, name):
    assert manager_client.get(url(name)).status_code == 200


@pytest.mark.parametrize(
    "name", ["detail", "deposit", "withdraw", "transfer", "dormant", "close", "loan"]
)
def test_account_pages(manager_client, account, name):
    assert manager_client.get(url(name, account)).status_code == 200
    account.refresh_from_db()
    assert account.balance == 0 and account.status == "ACTIVE"
    assert not LoanAccount.objects.exists()


@pytest.mark.parametrize("name", ["dormant", "close", "loan"])
def test_manager_permissions(client, staff_factory, account, name):
    client.force_login(staff_factory("teller"))
    for method in [client.get, client.post]:
        assert method(url(name, account), {"confirm": "on"}).status_code == 403
    assert b"Mark dormant" not in client.get(url("detail", account)).content


def test_authentication_and_staff(client, staff_factory):
    assert client.get(url("dashboard")).status_code == 302
    assert client.get(reverse("login")).status_code == 200
    user = staff_factory()
    user.is_staff = False
    user.save()
    client.force_login(user)
    assert client.get(url("dashboard")).status_code == 403


def test_unpermissioned_staff(client, django_user_model):
    user = django_user_model.objects.create_user(username="no-role", is_staff=True)
    client.force_login(user)
    assert client.get(url("dashboard")).status_code == 403


def test_teller_can_transact(client, staff_factory, account):
    client.force_login(staff_factory("teller"))
    assert client.post(url("deposit", account), {"amount": "100.00"}).status_code == 302


def test_csrf(account, staff_factory):
    client = Client(enforce_csrf_checks=True)
    client.force_login(staff_factory())
    assert client.post(url("deposit", account), {"amount": "100.00"}).status_code == 403
    account.refresh_from_db()
    assert account.balance == 0


def test_invalid_ids_and_methods(manager_client, account):
    assert manager_client.get(reverse("banking:detail", args=[uuid4()])).status_code == 404
    assert manager_client.get("/accounts/not-a-uuid/").status_code == 404
    assert manager_client.get(reverse("banking:receipt", args=[uuid4()])).status_code == 404
    assert manager_client.put(url("deposit", account)).status_code == 405
    assert manager_client.post(url("dashboard")).status_code == 405


def test_confirm_required(manager_client, account):
    manager_client.post(url("loan", account), {})
    assert not LoanAccount.objects.exists()
    assert manager_client.post(url("close", account), {"confirm": "on"}).status_code == 200


def test_business_error_visible(manager_client, account):
    response = manager_client.post(url("withdraw", account), {"amount": "1.00"})
    assert b"Insufficient funds" in response.content


@pytest.mark.parametrize(
    "exception,message",
    [
        (IntegrityError("duplicate"), b"already exists"),
        (OperationalError("busy"), b"database is busy"),
    ],
)
def test_database_error_visible(manager_client, account, exception, message):
    with patch("banking.services.deposit", side_effect=exception):
        response = manager_client.post(url("deposit", account), {"amount": "1.00"})
    assert message in response.content


def test_create_race_error(manager_client):
    with patch("banking.services.create_account", side_effect=IntegrityError("duplicate")):
        response = manager_client.post(
            url("create"),
            {
                "full_name": "Test",
                "email": "test@example.test",
                "phone_number": "0712345678",
                "national_id": "TEST9999",
                "account_type": "SAVINGS",
            },
        )
    assert b"already exists" in response.content


def test_filters_and_closed_visibility(manager_client, account_factory):
    active, closed = account_factory(), account_factory()
    services.mark_dormant(closed.public_id)
    services.close_account(closed.public_id)
    response = manager_client.get(url("accounts"))
    assert active.account_number.encode() in response.content
    assert closed.account_number.encode() not in response.content
    response = manager_client.get(url("accounts"), {"status": "CLOSED", "q": closed.account_number})
    assert closed.account_number.encode() in response.content
    response = manager_client.get(
        url("ledger"),
        {
            "account": closed.public_id,
            "type": "ACCOUNT_CLOSURE",
            "start": "2000-01-01",
            "end": "2100-01-01",
        },
    )
    assert len(response.context["entries"]) == 1
    response = manager_client.get(url("ledger"), {"start": "invalid"})
    assert len(response.context["entries"]) == 0


def test_seed_idempotent():
    output = StringIO()
    call_command("seed_demo", stdout=output)
    counts = [
        model.objects.count() for model in [Customer, BankAccount, LoanAccount, TransactionEntry]
    ]
    call_command("seed_demo", stdout=output)
    assert counts == [
        model.objects.count() for model in [Customer, BankAccount, LoanAccount, TransactionEntry]
    ]
    assert counts[:3] == [5, 5, 1]
    from django.contrib.auth import get_user_model

    manager = get_user_model().objects.get(username="demo_manager")
    assert manager.has_perm("banking.manage_accounts")
    assert not manager.has_usable_password()


def test_admin_is_read_only(account):
    model_admin = admin.site._registry[TransactionEntry]
    assert not model_admin.has_add_permission(None)
    assert not model_admin.has_delete_permission(None)
    assert not model_admin.has_change_permission(None)
    assert "amount" in model_admin.get_readonly_fields(None)


@override_settings(DEBUG=False)
def test_friendly_404(manager_client):
    assert b"That record" in manager_client.get("/missing/").content
