from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand
from django.db import transaction

from banking import services
from banking.models import Customer


class Command(BaseCommand):
    help = "Create fictional demo data and staff roles without setting reusable passwords."

    @transaction.atomic
    def handle(self, *args, **options):
        teller, _ = Group.objects.get_or_create(name="Teller")
        manager, _ = Group.objects.get_or_create(name="Manager")
        view_perms = Permission.objects.filter(
            content_type__app_label="banking", codename__startswith="view_"
        )
        operate = Permission.objects.get(
            codename="operate_accounts", content_type__app_label="banking"
        )
        manage = Permission.objects.get(
            codename="manage_accounts", content_type__app_label="banking"
        )
        teller.permissions.set([*view_perms, operate])
        manager.permissions.set([*view_perms, operate, manage])
        for username, group in [("demo_teller", teller), ("demo_manager", manager)]:
            user, created = get_user_model().objects.get_or_create(
                username=username, defaults={"is_staff": True}
            )
            if created:
                user.set_unusable_password()
                user.save()
            user.groups.add(group)
        names = ["Amani Demo", "Zuri Demo", "Baraka Demo", "Neema Demo", "Imani Demo"]
        created_accounts = {}
        for index, name in enumerate(names):
            email = f"customer{index + 1}@example.test"
            if not Customer.objects.filter(email=email).exists():
                created_accounts[index] = services.create_account(
                    account_type="SAVINGS" if index % 2 == 0 else "CURRENT",
                    full_name=name,
                    email=email,
                    phone_number=f"+25470000000{index}",
                    national_id=f"DEMO{index:04}",
                )
        if 0 in created_accounts:
            services.deposit(created_accounts[0].public_id, "25000.00", "Demo opening deposit")
            services.withdraw(created_accounts[0].public_id, "5000.00")
        if 0 in created_accounts and 1 in created_accounts:
            services.transfer(
                created_accounts[0].public_id, created_accounts[1].public_id, "2500.00"
            )
        if 2 in created_accounts:
            services.mark_dormant(created_accounts[2].public_id)
        if 3 in created_accounts:
            services.mark_dormant(created_accounts[3].public_id)
            services.close_account(created_accounts[3].public_id)
        if 4 in created_accounts:
            services.disburse_loan(created_accounts[4].public_id)
        self.stdout.write(self.style.SUCCESS("Demo data ready. No passwords were set or changed."))
        self.stdout.write("Set a local password with: python manage.py changepassword demo_manager")
