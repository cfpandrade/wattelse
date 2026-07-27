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
CONF_START_DATE: Final = "start_date"
CONF_MANAGE_ENERGY_DASHBOARD: Final = "manage_energy_dashboard"

DEFAULT_NAME: Final = "Electricity"
DEFAULT_CURRENCY: Final = "EUR"
DEFAULT_LEVY_NAME: Final = "PSO Levy"

# Charge kinds -> one phantom energy sensor + one cost sensor each
KIND_STANDING: Final = "standing_charge"
KIND_LEVY: Final = "levy"
KIND_VAT: Final = "vat"

# Bill order. The Energy dashboard lists its sources in the order they are stored, so
# this is what decides how the charges read on screen: the consumption tariffs the user
# already had, then the levy, then the standing charge, and VAT last -- because VAT is a
# percentage of everything above it and only makes sense once they have all been listed.
CHARGE_ORDER: Final = (KIND_LEVY, KIND_STANDING, KIND_VAT)

# Money is published to the cent. Charges accrue in fractions of one -- a standing
# charge of 0.6798 a day is worth 0.00047 a minute -- but what reaches the dashboard is
# rounded, because the dashboard totals the stored values and a row that displays 12.34
# while storing 12.3412 makes the total disagree with the rows above it by a few cents.
CURRENCY_DECIMALS: Final = 2

# How often the time-based charges accrue. One minute keeps the hourly
# statistics smooth without putting any real load on the event loop.
ACCRUAL_INTERVAL_MINUTES: Final = 1

# Where the record of what has already been backfilled lives, so a restart does not
# rewrite history it has written before.
STORAGE_KEY: Final = f"{DOMAIN}.backfill"
STORAGE_VERSION: Final = 1

SERVICE_SET_TOTAL: Final = "set_total"
ATTR_VALUE: Final = "value"
