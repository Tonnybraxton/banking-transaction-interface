import pytest
from django.contrib.auth.models import Permission

from banking.services import create_account


@pytest.fixture
def account_factory(db):
    count = 0

    def make(**kwargs):
        nonlocal count
        count += 1
        data = dict(
            full_name=f"Customer {count}",
            email=f"c{count}@example.test",
            phone_number=f"071234{count:04}",
            national_id=f"TEST{count:04}",
            account_type="SAVINGS",
        )
        data.update(kwargs)
        return create_account(**data)

    return make


@pytest.fixture
def account(account_factory):
    return account_factory()


@pytest.fixture
def staff_factory(db, django_user_model):
    def make(role="manager"):
        user = django_user_model.objects.create_user(username=role, is_staff=True)
        names = ["operate_accounts"]
        if role == "manager":
            names.append("manage_accounts")
        user.user_permissions.set(Permission.objects.filter(codename__in=names))
        return user

    return make


@pytest.fixture
def manager_client(client, staff_factory):
    client.force_login(staff_factory())
    return client
