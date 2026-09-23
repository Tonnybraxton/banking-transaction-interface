from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError

from .models import BankAccount, Customer, TransactionEntry
from .validators import MAX_TRANSACTION, normalize_phone


class StyledForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = (
                "form-check-input"
                if isinstance(field.widget, forms.CheckboxInput)
                else "form-control"
            )


class CreateAccountForm(StyledForm):
    customer = forms.ModelChoiceField(
        queryset=Customer.objects.order_by("full_name"),
        required=False,
        empty_label="Create a new customer",
        help_text="Select an existing customer or complete all customer fields below.",
    )
    full_name = forms.CharField(max_length=150, required=False)
    email = forms.EmailField(required=False)
    phone_number = forms.CharField(
        max_length=30, required=False, help_text="Kenyan mobile, e.g. 0712 345 678"
    )
    national_id = forms.RegexField(
        r"^[A-Za-z0-9-]{4,20}$",
        required=False,
        help_text="Use fictional identity details for this demo.",
    )
    account_type = forms.ChoiceField(choices=BankAccount.Type)

    def clean(self):
        data = super().clean()
        if data.get("customer"):
            return data
        for name in ["full_name", "email", "phone_number", "national_id"]:
            if not data.get(name):
                self.add_error(name, "Required for a new customer.")
        if self.errors:
            return data
        try:
            data["phone_number"] = normalize_phone(data["phone_number"])
        except ValidationError as exc:
            self.add_error("phone_number", exc)
            return data
        data["email"] = data["email"].lower()
        data["national_id"] = data["national_id"].upper()
        for name in ["email", "phone_number", "national_id"]:
            if Customer.objects.filter(**{name: data[name]}).exists():
                self.add_error(name, "Already registered. Select the existing customer instead.")
        return data


class MoneyForm(StyledForm):
    amount = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_value=MAX_TRANSACTION,
        max_digits=10,
        decimal_places=2,
        label="Amount (KES)",
        widget=forms.NumberInput(attrs={"step": "0.01", "placeholder": "0.00"}),
    )
    description = forms.CharField(max_length=240, required=False, label="Note (optional)")


class TransferForm(MoneyForm):
    destination = forms.ModelChoiceField(
        queryset=BankAccount.objects.none(), to_field_name="public_id", label="Recipient account"
    )

    def __init__(self, *args, account, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destination"].queryset = (
            BankAccount.objects.filter(status="ACTIVE")
            .exclude(pk=account.pk)
            .select_related("customer")
        )


class ConfirmationForm(StyledForm):
    confirm = forms.BooleanField(label="I understand and confirm this action.")


class LedgerFilterForm(StyledForm):
    account = forms.ModelChoiceField(
        queryset=BankAccount.objects.select_related("customer").all(),
        to_field_name="public_id",
        required=False,
    )
    type = forms.ChoiceField(
        choices=[("", "All transaction types"), *TransactionEntry.Type.choices], required=False
    )
    start = forms.DateField(
        required=False, label="From date", widget=forms.DateInput(attrs={"type": "date"})
    )
    end = forms.DateField(
        required=False, label="To date", widget=forms.DateInput(attrs={"type": "date"})
    )

    def clean(self):
        data = super().clean()
        if data.get("start") and data.get("end") and data["start"] > data["end"]:
            raise ValidationError("The end date must be on or after the start date.")
        return data
