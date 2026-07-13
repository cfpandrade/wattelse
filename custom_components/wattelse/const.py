"""Constants for the WattElse integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "wattelse"

# Config / options keys
CONF_NAME: Final = "name"
CONF_CURRENCY: Final = "currency"
CONF_STANDING_CHARGE: Final = "standing_charge"
CONF_LEVY_AMOUNT: Final = "levy_amount"
CONF_LEVY_NAME: Final = "levy_name"
CONF_VAT_RATE: Final = "vat_rate"
CONF_VAT_SOURCES: Final = "vat_sources"
CONF_SHOW_RATE_IN_NAME: Final = "show_rate_in_name"
CONF_MANAGE_ENERGY_DASHBOARD: Final = "manage_energy_dashboard"

DEFAULT_NAME: Final = "Electricity"
DEFAULT_CURRENCY: Final = "EUR"
DEFAULT_LEVY_NAME: Final = "Levy"

# Charge kinds -> one phantom energy sensor + one cost sensor each
KIND_STANDING: Final = "standing_charge"
KIND_LEVY: Final = "levy"
KIND_VAT: Final = "vat"

# How often the time-based charges accrue. One minute keeps the hourly
# statistics smooth without putting any real load on the event loop.
ACCRUAL_INTERVAL_MINUTES: Final = 1

SERVICE_SET_TOTAL: Final = "set_total"
ATTR_VALUE: Final = "value"
