import pytest

from banking.forms import CreateAccountForm, LedgerFilterForm, MoneyForm

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("value", ["0", "-1", "1.111", "10000000.01", "NaN", "abc"])
def test_money_form_rejects_invalid(value):
    assert not MoneyForm({"amount": value}).is_valid()


def test_create_form_normalizes():
    form = CreateAccountForm(
        {
            "full_name": " Demo User ",
            "email": "TEST@EXAMPLE.TEST",
            "phone_number": "0712 345 678",
            "national_id": "test0001",
            "account_type": "SAVINGS",
        }
    )
    assert form.is_valid(), form.errors
    assert form.cleaned_data["phone_number"] == "+254712345678"
    assert form.cleaned_data["email"] == "test@example.test"


def test_create_form_missing_and_duplicates(account):
    assert not CreateAccountForm({"account_type": "SAVINGS"}).is_valid()
    form = CreateAccountForm(
        {
            "full_name": "Duplicate",
            "email": account.customer.email,
            "phone_number": account.customer.phone_number,
            "national_id": account.customer.national_id,
            "account_type": "SAVINGS",
        }
    )
    assert not form.is_valid()
    assert {"email", "phone_number", "national_id"} <= set(form.errors)
    assert CreateAccountForm(
        {"customer": account.customer_id, "account_type": "CURRENT"}
    ).is_valid()


def test_create_form_invalid_phone():
    form = CreateAccountForm(
        {
            "full_name": "Demo",
            "email": "demo@example.test",
            "phone_number": "123",
            "national_id": "DEMO0001",
            "account_type": "SAVINGS",
        }
    )
    assert not form.is_valid()
    assert "phone_number" in form.errors


def test_invalid_date_filter():
    assert not LedgerFilterForm({"start": "2026-09-23", "end": "2026-09-01"}).is_valid()
