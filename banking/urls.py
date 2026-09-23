from django.urls import path

from . import views

app_name = "banking"
urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("accounts/", views.accounts, name="accounts"),
    path("accounts/new/", views.create_account, name="create"),
    path("accounts/<uuid:public_id>/", views.detail, name="detail"),
    path("accounts/<uuid:public_id>/deposit/", views.money, {"action": "deposit"}, name="deposit"),
    path(
        "accounts/<uuid:public_id>/withdraw/", views.money, {"action": "withdraw"}, name="withdraw"
    ),
    path(
        "accounts/<uuid:public_id>/transfer/", views.money, {"action": "transfer"}, name="transfer"
    ),
    path(
        "accounts/<uuid:public_id>/dormant/",
        views.manage_account,
        {"action": "dormant"},
        name="dormant",
    ),
    path(
        "accounts/<uuid:public_id>/close/", views.manage_account, {"action": "close"}, name="close"
    ),
    path("accounts/<uuid:public_id>/loan/", views.manage_account, {"action": "loan"}, name="loan"),
    path("transactions/", views.ledger, name="ledger"),
    path("transactions/<uuid:reference>/", views.receipt, name="receipt"),
]
