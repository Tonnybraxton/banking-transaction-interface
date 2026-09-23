import re
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError

MAX_TRANSACTION = Decimal("10000000.00")
MAX_BALANCE = Decimal("999999999999.99")


def normalize_phone(value):
    value = re.sub(r"[\s()-]", "", value)
    if value.startswith("0"):
        value = "+254" + value[1:]
    elif value.startswith("254"):
        value = "+" + value
    if not re.fullmatch(r"\+254[17]\d{8}", value):
        raise ValidationError("Enter a Kenyan mobile number, e.g. 0712 345 678.")
    return value


def validate_amount(value):
    if isinstance(value, (float, bool)):
        raise ValidationError("Use an exact decimal amount.")
    try:
        amount = Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError("Enter a valid amount.") from exc
    if not amount.is_finite() or amount <= 0 or amount > MAX_TRANSACTION:
        raise ValidationError("Amount must be between KES 0.01 and KES 10,000,000.00.")
    if amount.as_tuple().exponent < -2:
        raise ValidationError("Use no more than two decimal places.")
    return amount.quantize(Decimal("0.01"))
