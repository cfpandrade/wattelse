"""Sensors for the WattElse integration.

Each charge produces two entities:

  * a *phantom energy* sensor, permanently 0 kWh. The Energy dashboard refuses to
    create a source without an energy statistic, so this is what we give it. Its
    friendly name is what the dashboard shows as the source title, which is why the
    rate is rendered into that name.
  * a *cost* sensor in the configured currency, which is what actually carries the
    money.

All cost sensors accrue **incrementally**: they keep a running total and add to it as
time passes (or as the tracked sensors go up). They never recompute from a start date
multiplied by the current rate. That matters: when a rate changes -- your supplier
raises the standing charge, the government moves VAT -- only the future is affected and
the history you have already recorded stays true to what you were actually billed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import ExtraStoredData
from homeassistant.util import dt as dt_util

from .const import (
    ACCRUAL_INTERVAL_MINUTES,
    CONF_CURRENCY,
    CONF_LEVY_AMOUNT,
    CONF_LEVY_NAME,
    CONF_NAME,
    CONF_SHOW_RATE_IN_NAME,
    CONF_STANDING_CHARGE,
    CONF_VAT_RATE,
    CONF_VAT_SOURCES,
    DEFAULT_CURRENCY,
    DEFAULT_LEVY_NAME,
    DEFAULT_NAME,
    DOMAIN,
    KIND_LEVY,
    KIND_STANDING,
    KIND_VAT,
)

_LOGGER = logging.getLogger(__name__)

UNAVAILABLE_STATES = ("unknown", "unavailable", "", None)


def _options(entry: ConfigEntry) -> dict[str, Any]:
    """Options win over the values captured at install time."""
    return {**entry.data, **entry.options}


class ChargeExtraData(ExtraStoredData):
    """The bits of a charge sensor that must survive a restart."""

    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    def as_dict(self) -> dict[str, Any]:
        return self.data


class PhantomEnergySensor(SensorEntity):
    """A 0 kWh sensor. It exists only so the Energy dashboard will accept the source."""

    _attr_should_poll = False
    _attr_native_value = 0
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, entry: ConfigEntry, kind: str, name: str, device: DeviceInfo) -> None:
        self._attr_unique_id = f"{entry.entry_id}_{kind}_energy"
        self._attr_name = name
        self._attr_device_info = device


class BaseCostSensor(RestoreSensor):
    """A money sensor that keeps a running total and only ever grows."""

    _attr_should_poll = False
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(
        self, entry: ConfigEntry, kind: str, name: str, currency: str, device: DeviceInfo
    ) -> None:
        self._entry = entry
        self._kind = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}_cost"
        self._attr_name = name
        self._attr_native_unit_of_measurement = currency
        self._attr_device_info = device
        self._total: float = 0.0
        self._on_accrued: list[Callable[[float], None]] = []
        self._added = False

    @property
    def native_value(self) -> float:
        return round(self._total, 5)

    @property
    def extra_restore_state_data(self) -> ChargeExtraData:
        return ChargeExtraData(self._state_to_restore())

    def _state_to_restore(self) -> dict[str, Any]:
        return {"total": self._total}

    def _restore(self, data: dict[str, Any]) -> None:
        self._total = float(data.get("total") or 0.0)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (stored := await self.async_get_last_extra_data()) is not None:
            try:
                self._restore(stored.as_dict())
            except (TypeError, ValueError):
                _LOGGER.warning("Could not restore %s; starting from zero", self.entity_id)
        self._added = True

    @callback
    def _write(self) -> None:
        """Write state, but only once Home Assistant actually has this entity.

        The fixed charges notify the VAT sensor the moment they accrue, and the very
        first accrual happens while the platform is still adding entities -- so VAT can
        be told about money before it exists. The total is still accumulated; it simply
        lands on the next write.
        """
        if self._added:
            self.async_write_ha_state()

    def add_listener(self, cb: Callable[[float], None]) -> None:
        """Register a callback fired with every increment. Used to feed the VAT sensor."""
        self._on_accrued.append(cb)

    def _accrue(self, amount: float) -> None:
        if amount <= 0:
            return
        self._total += amount
        for cb in self._on_accrued:
            cb(amount)
        self._write()

    @callback
    def set_total(self, value: float) -> None:
        """Overwrite the running total (used by the set_total service)."""
        self._total = float(value)
        self._write()


class StandingChargeSensor(BaseCostSensor):
    """A per-day charge, accrued continuously.

    Accruing by the minute rather than in one lump per day keeps the hourly statistics
    -- and therefore the Energy dashboard's hourly bars -- smooth.
    """

    def __init__(self, entry, name, currency, device, rate_per_day: float) -> None:
        super().__init__(entry, KIND_STANDING, name, currency, device)
        self._rate = rate_per_day
        self._last: datetime | None = None

    def _state_to_restore(self) -> dict[str, Any]:
        return {
            "total": self._total,
            "last": self._last.isoformat() if self._last else None,
        }

    def _restore(self, data: dict[str, Any]) -> None:
        super()._restore(data)
        if raw := data.get("last"):
            self._last = dt_util.parse_datetime(raw)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Charges keep running while Home Assistant is down, so the first tick after a
        # restart deliberately settles the whole offline gap.
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(minutes=ACCRUAL_INTERVAL_MINUTES)
            )
        )
        self._tick(dt_util.utcnow())

    @callback
    def _tick(self, now: datetime) -> None:
        if self._last is None:
            self._last = now
            self._write()
            return
        elapsed_days = (now - self._last).total_seconds() / 86400
        self._last = now
        if elapsed_days > 0 and self._rate:
            self._accrue(elapsed_days * self._rate)
        else:
            self._write()


class LevySensor(BaseCostSensor):
    """A flat charge billed once a month (Ireland's PSO levy, for example).

    This is deliberately NOT spread across the days of the month. A flat monthly fee
    prorated by day can never be right for both 30- and 31-day billing cycles: it
    overshoots on the long ones and undershoots on the short ones. Suppliers date the
    charge at month end, so we add the whole amount when the month rolls over. Billing
    cycles that run mid-month to mid-month (say the 22nd to the 21st) always contain
    exactly one month boundary, so they always get exactly one levy.
    """

    def __init__(self, entry, name, currency, device, amount_per_month: float) -> None:
        super().__init__(entry, KIND_LEVY, name, currency, device)
        self._amount = amount_per_month
        self._last_month: tuple[int, int] | None = None

    def _state_to_restore(self) -> dict[str, Any]:
        return {"total": self._total, "last_month": self._last_month}

    def _restore(self, data: dict[str, Any]) -> None:
        super()._restore(data)
        if last := data.get("last_month"):
            self._last_month = (int(last[0]), int(last[1]))

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_interval(
                self.hass, self._tick, timedelta(minutes=ACCRUAL_INTERVAL_MINUTES)
            )
        )
        self._tick(dt_util.utcnow())

    @callback
    def _tick(self, now: datetime) -> None:
        local = dt_util.as_local(now)
        current = (local.year, local.month)
        if self._last_month is None:
            self._last_month = current
            self._write()
            return
        months = (current[0] - self._last_month[0]) * 12 + (current[1] - self._last_month[1])
        if months <= 0:
            return
        self._last_month = current
        if self._amount:
            self._accrue(months * self._amount)
        else:
            self._write()


class VatSensor(BaseCostSensor):
    """VAT charged on the net of the tracked cost sensors plus our own fixed charges.

    It accumulates a percentage of every *increment* it sees, never a percentage of the
    running totals. So if the VAT rate changes, past tax stays at the old rate -- which
    is what your bills actually said -- and only new consumption is taxed at the new one.
    """

    def __init__(
        self,
        entry,
        name,
        currency,
        device,
        rate_percent: float,
        sources: list[str],
    ) -> None:
        super().__init__(entry, KIND_VAT, name, currency, device)
        self._rate = rate_percent / 100
        self._sources = sources
        self._seen: dict[str, float] = {}

    def _state_to_restore(self) -> dict[str, Any]:
        return {"total": self._total, "seen": self._seen}

    def _restore(self, data: dict[str, Any]) -> None:
        super()._restore(data)
        seen = data.get("seen") or {}
        self._seen = {k: float(v) for k, v in seen.items()}

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._sources:
            self.async_on_remove(
                async_track_state_change_event(self.hass, self._sources, self._source_changed)
            )
            # Seed the baselines so we never tax a sensor's whole lifetime total on the
            # first update after a fresh install.
            for entity_id in self._sources:
                if entity_id in self._seen:
                    continue
                state = self.hass.states.get(entity_id)
                if state and state.state not in UNAVAILABLE_STATES:
                    try:
                        self._seen[entity_id] = float(state.state)
                    except ValueError:
                        continue

    @callback
    def _source_changed(self, event: Event[EventStateChangedData]) -> None:
        new_state = event.data["new_state"]
        if new_state is None or new_state.state in UNAVAILABLE_STATES:
            return
        try:
            value = float(new_state.state)
        except ValueError:
            return

        entity_id = event.data["entity_id"]
        previous = self._seen.get(entity_id)
        self._seen[entity_id] = value

        if previous is None:
            return
        delta = value - previous
        if delta <= 0:
            # A cost sensor that went backwards was reset, not refunded.
            return
        self.add_net(delta)

    @callback
    def add_net(self, net_amount: float) -> None:
        """Tax a net increment. Called by the fixed-charge sensors too."""
        if self._rate:
            self._accrue(net_amount * self._rate)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the charges for a config entry."""
    opts = _options(entry)
    base = opts.get(CONF_NAME) or DEFAULT_NAME
    currency = opts.get(CONF_CURRENCY) or DEFAULT_CURRENCY
    standing = float(opts.get(CONF_STANDING_CHARGE) or 0)
    levy = float(opts.get(CONF_LEVY_AMOUNT) or 0)
    levy_name = opts.get(CONF_LEVY_NAME) or DEFAULT_LEVY_NAME
    vat = float(opts.get(CONF_VAT_RATE) or 0)
    vat_sources: list[str] = list(opts.get(CONF_VAT_SOURCES) or [])
    show_rate = opts.get(CONF_SHOW_RATE_IN_NAME, True)

    device = DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=base,
        manufacturer="WattElse",
        entry_type=DeviceEntryType.SERVICE,
    )

    def titled(label: str, rate: str) -> str:
        # The dashboard shows the *energy* sensor's name, so the rate is baked in there:
        # the Sources list ends up documenting the tariff it is charging you.
        return f"{base} {label} {rate}" if show_rate and rate else f"{base} {label}"

    entities: list[SensorEntity] = []
    costs: dict[str, BaseCostSensor] = {}
    kinds: list[str] = []

    vat_sensor: VatSensor | None = None
    if vat > 0:
        vat_sensor = VatSensor(
            entry, f"{base} VAT Cost", currency, device, vat, vat_sources
        )

    if standing > 0:
        sensor = StandingChargeSensor(
            entry, f"{base} Standing Charge Cost", currency, device, standing
        )
        if vat_sensor:
            sensor.add_listener(vat_sensor.add_net)
        costs[KIND_STANDING] = sensor
        energy = PhantomEnergySensor(
            entry,
            KIND_STANDING,
            titled("Standing Charge", f"{standing:g} {currency}/day"),
            device,
        )
        entities += [energy, sensor]
        kinds.append(KIND_STANDING)

    if levy > 0:
        sensor = LevySensor(entry, f"{base} {levy_name} Cost", currency, device, levy)
        if vat_sensor:
            sensor.add_listener(vat_sensor.add_net)
        costs[KIND_LEVY] = sensor
        energy = PhantomEnergySensor(
            entry, KIND_LEVY, titled(levy_name, f"{levy:g} {currency}/month"), device
        )
        entities += [energy, sensor]
        kinds.append(KIND_LEVY)

    if vat_sensor:
        costs[KIND_VAT] = vat_sensor
        energy = PhantomEnergySensor(
            entry, KIND_VAT, titled("VAT", f"{vat:g}%"), device
        )
        entities += [energy, vat_sensor]
        kinds.append(KIND_VAT)

    async_add_entities(entities)

    # Entity ids are assigned while the entities are being added, so they are not
    # readable yet here. __init__ resolves them from the entity registry once this
    # platform has finished setting up, and only then touches the Energy dashboard.
    store = hass.data[DOMAIN][entry.entry_id]
    store["cost_sensors"] = costs
    store["kinds"] = kinds
