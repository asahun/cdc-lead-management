"""
Formatting utilities for currency, dates, and other display values.
"""

from decimal import Decimal, InvalidOperation


def format_currency(value):
    """Format a value as currency string."""
    if value is None or value == "":
        return "—"

    if isinstance(value, Decimal):
        decimal_value = value
    else:
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError, TypeError):
            return str(value)

    return f"${decimal_value:,.2f}"

