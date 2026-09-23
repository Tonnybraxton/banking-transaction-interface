from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import IntegrityError, OperationalError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from . import selectors, services
from .forms import ConfirmationForm, CreateAccountForm, LedgerFilterForm, MoneyForm, TransferForm
from .models import BankAccount, TransactionEntry


def staff_permission(manager=False):
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            permission = "banking.manage_accounts" if manager else "banking.operate_accounts"
            if not request.user.is_staff or not request.user.has_perm(permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


@staff_permission()
@require_http_methods(["GET"])
def dashboard(request):
    return render(
        request,
        "banking/dashboard.html",
        {
            "stats": selectors.dashboard_stats(),
            "accounts": selectors.account_list()[:5],
            "entries": selectors.ledger_entries()[:6],
        },
    )


@staff_permission()
@require_http_methods(["GET"])
def accounts(request):
    query, status = request.GET.get("q", "").strip(), request.GET.get("status", "")
    page = Paginator(selectors.account_list(query, status), 15).get_page(request.GET.get("page"))
    return render(
        request,
        "banking/accounts.html",
        {
            "page_obj": page,
            "accounts": page,
            "q": query,
            "status": status,
            "statuses": BankAccount.Status.choices,
        },
    )


def _error(form, exc):
    if isinstance(exc, ValidationError):
        form.add_error(None, " ".join(exc.messages))
    elif isinstance(exc, IntegrityError):
        form.add_error(None, "A record with these details already exists. Check and try again.")
    else:
        form.add_error(None, "The database is busy. No changes were saved. Please try again.")


@staff_permission()
@require_http_methods(["GET", "POST"])
def create_account(request):
    form = CreateAccountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            account = services.create_account(**form.cleaned_data)
        except (ValidationError, IntegrityError, OperationalError) as exc:
            _error(form, exc)
        else:
            messages.success(request, "Account created. You're ready to make the first deposit.")
            return redirect("banking:detail", public_id=account.public_id)
    return render(
        request,
        "banking/form.html",
        {
            "form": form,
            "title": "Open a new account",
            "subtitle": "A fresh start for your customer's money.",
            "button": "Create account",
        },
    )


@staff_permission()
@require_http_methods(["GET"])
def detail(request, public_id):
    account = get_object_or_404(
        BankAccount.objects.select_related("customer", "loan"), public_id=public_id
    )
    return render(
        request, "banking/detail.html", {"account": account, "entries": account.entries.all()[:25]}
    )


@staff_permission()
@require_http_methods(["GET", "POST"])
def money(request, public_id, action):
    account = get_object_or_404(BankAccount, public_id=public_id)
    form = (
        TransferForm(request.POST or None, account=account)
        if action == "transfer"
        else MoneyForm(request.POST or None)
    )
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        try:
            if action == "transfer":
                entry = services.transfer(
                    public_id, data["destination"].public_id, data["amount"], data["description"]
                )
            else:
                entry = getattr(services, action)(public_id, data["amount"], data["description"])
        except (ValidationError, IntegrityError, OperationalError) as exc:
            _error(form, exc)
        else:
            messages.success(request, "Transaction completed and recorded in the ledger.")
            return redirect("banking:receipt", reference=entry.reference)
    titles = {
        "deposit": "Deposit funds",
        "withdraw": "Withdraw funds",
        "transfer": "Transfer funds",
    }
    return render(
        request,
        "banking/form.html",
        {
            "form": form,
            "account": account,
            "title": titles[action],
            "subtitle": "Every movement is securely recorded in the audit ledger.",
            "button": titles[action],
        },
    )


@staff_permission(manager=True)
@require_http_methods(["GET", "POST"])
def manage_account(request, public_id, action):
    account = get_object_or_404(BankAccount, public_id=public_id)
    form = ConfirmationForm(request.POST or None)
    config = {
        "dormant": (
            "Mark account dormant",
            "Requires a zero balance and no outstanding loan. Dormant accounts cannot transact.",
            services.mark_dormant,
        ),
        "close": (
            "Close dormant account",
            "This is a soft delete: the account closes permanently, while all financial records "
            "remain available for audit. Requires dormancy, zero funds and no outstanding loan.",
            services.close_account,
        ),
        "loan": (
            "Create & Disburse KES 10,000 Loan",
            "This one-time demo loan credits exactly KES 10,000.00 in demo money. Interest is 0%. "
            "The outstanding loan prevents account closure.",
            services.disburse_loan,
        ),
    }
    title, subtitle, service = config[action]
    if request.method == "POST" and form.is_valid():
        try:
            result = service(public_id)
        except (ValidationError, IntegrityError, OperationalError) as exc:
            _error(form, exc)
        else:
            messages.success(request, f"{title}: completed.")
            if isinstance(result, TransactionEntry):
                return redirect("banking:receipt", reference=result.reference)
            return redirect("banking:detail", public_id=public_id)
    return render(
        request,
        "banking/form.html",
        {
            "form": form,
            "account": account,
            "title": title,
            "subtitle": subtitle,
            "button": title,
            "danger": action == "close",
        },
    )


@staff_permission()
@require_http_methods(["GET"])
def receipt(request, reference):
    entry = get_object_or_404(selectors.ledger_entries(), reference=reference)
    paired = (
        selectors.ledger_entries().filter(transfer_group_reference=entry.transfer_group_reference)
        if entry.transfer_group_reference
        else []
    )
    return render(request, "banking/receipt.html", {"entry": entry, "paired": paired})


@staff_permission()
@require_http_methods(["GET"])
def ledger(request):
    form = LedgerFilterForm(request.GET)
    entries = (
        selectors.ledger_entries(form.cleaned_data)
        if form.is_valid()
        else TransactionEntry.objects.none()
    )
    page = Paginator(entries, 20).get_page(request.GET.get("page"))
    return render(request, "banking/ledger.html", {"form": form, "entries": page, "page_obj": page})
