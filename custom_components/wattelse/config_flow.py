"""Config and options flow for WattElse."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    DateSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)
import voluptuous as vol

from .const import (
    CONF_CURRENCY,
    CONF_LEVY_AMOUNT,
    CONF_LEVY_NAME,
    CONF_NAME,
    CONF_SHOW_RATE_IN_NAME,
    CONF_STANDING_CHARGE,
    CONF_START_DATE,
    CONF_VAT_RATE,
    CONF_VAT_SOURCES,
    DEFAULT_CURRENCY,
    DEFAULT_LEVY_NAME,
    DEFAULT_NAME,
    DOMAIN,
)


def _money() -> NumberSelector:
    # step="any" and not a small float: Home Assistant's NumberSelector rejects any step
    # below 0.001, and electricity rates routinely have four decimals (0.6798 EUR/day).
    return NumberSelector(
        NumberSelectorConfig(min=0, step="any", mode=NumberSelectorMode.BOX)
    )


def _schema(defaults: dict[str, Any]) -> vol.Schema:
    """The one form, used both at install time and in the options flow.

    Everything except the name is optional: leave a charge at 0 and no sensor is
    created for it, so a supplier with no levy simply doesn't get a levy row.
    """
    return vol.Schema(
        {
            vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, DEFAULT_NAME)): TextSelector(),
            vol.Required(
                CONF_CURRENCY, default=defaults.get(CONF_CURRENCY, DEFAULT_CURRENCY)
            ): TextSelector(),
            vol.Optional(
                CONF_STANDING_CHARGE, default=defaults.get(CONF_STANDING_CHARGE, 0)
            ): _money(),
            vol.Optional(
                CONF_LEVY_NAME, default=defaults.get(CONF_LEVY_NAME, DEFAULT_LEVY_NAME)
            ): TextSelector(),
            vol.Optional(
                CONF_LEVY_AMOUNT, default=defaults.get(CONF_LEVY_AMOUNT, 0)
            ): _money(),
            vol.Optional(CONF_VAT_RATE, default=defaults.get(CONF_VAT_RATE, 0)): NumberSelector(
                NumberSelectorConfig(min=0, max=100, step="any", mode=NumberSelectorMode.BOX)
            ),
            vol.Optional(
                CONF_VAT_SOURCES, default=defaults.get(CONF_VAT_SOURCES, [])
            ): EntitySelector(
                EntitySelectorConfig(domain="sensor", device_class="monetary", multiple=True)
            ),
            vol.Optional(
                CONF_SHOW_RATE_IN_NAME, default=defaults.get(CONF_SHOW_RATE_IN_NAME, True)
            ): bool,
            vol.Optional(
                CONF_START_DATE, description={"suggested_value": defaults.get(CONF_START_DATE)}
            ): DateSelector(),
        }
    )


class WattElseConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the charges that are on the bill but not in the Energy dashboard."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(entry: ConfigEntry) -> OptionsFlow:
        return WattElseOptionsFlow()


class WattElseOptionsFlow(OptionsFlow):
    """Edit the rates later -- VAT changes, the supplier raises the standing charge.

    Only the future is affected: the sensors keep their running totals across the
    reload, so what you were billed in the past stays as it was billed.
    """

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
