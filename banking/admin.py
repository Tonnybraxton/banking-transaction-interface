from django.contrib import admin

from .models import BankAccount, Customer, LoanAccount, TransactionEntry


class AuditAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return [field.name for field in self.model._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Customer)
class CustomerAdmin(AuditAdmin):
    list_display = ["full_name", "email", "created_at"]
    search_fields = ["full_name", "email"]


@admin.register(BankAccount)
class BankAccountAdmin(AuditAdmin):
    list_display = ["account_number", "customer", "balance", "status"]
    list_filter = ["status", "account_type"]


@admin.register(TransactionEntry)
class TransactionAdmin(AuditAdmin):
    list_display = ["reference", "account", "transaction_type", "amount", "created_at"]
    list_filter = ["transaction_type"]


@admin.register(LoanAccount)
class LoanAdmin(AuditAdmin):
    list_display = ["loan_number", "bank_account", "outstanding_balance", "status"]
