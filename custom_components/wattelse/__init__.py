"""WattElse -- everything on your electricity bill that isn't kilowatt-hours.

Home Assistant's Energy dashboard can only do kWh x price. Real bills also carry a
standing charge, a flat monthly levy and VAT, and those are usually a quarter of what
you actually pay. This integration models them as sensors and registers them on the
Energy dashboard so its total finally matches the bill.
"""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant import loader
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.storage import Store
import voluptuous as vol

from .backfill import async_backfill
from .const import (
    ATTR_VALUE,
    CONF_CURRENCY,
    CONF_LEVY_AMOUNT,
    CONF_STANDING_CHARGE,
    CONF_START_DATE,
    CONF_VAT_RATE,
    CONF_VAT_SOURCES,
    DEFAULT_CURRENCY,
    DOMAIN,
    SERVICE_SET_TOTAL,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .energy_dashboard import (
    async_add_sources,
    async_detect_vat_sources,
    async_remove_sources,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SET_TOTAL_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): cv.entity_ids,
        vol.Required(ATTR_VALUE): vol.Coerce(float),
    }
)


def integration_version(hass: HomeAssistant) -> str:
    """Our own version, so an upgrade can decide to redo work the old code got wrong."""
    integration = loader.async_get_loaded_integration(hass, DOMAIN)
    return integration.version and str(integration.version) or "0"


def _entity_ids(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, str]:
    """Map each of our unique_id suffixes to the entity id HA actually assigned.

    Entity ids are not known inside the sensor platform (they are handed out while the
    entities are being added), so everything that needs them waits until the platform
    has finished and then reads them back out of the registry.
    """
    registry = er.async_get(hass)
    found: dict[str, str] = {}
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        suffix = entity.unique_id.removeprefix(f"{entry.entry_id}_")
        found[suffix] = entity.entity_id
    return found


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up WattElse from a config entry."""
    # Which cost sensors VAT is charged on. The user can name them explicitly, but by
    # default we read them off the Energy dashboard: every grid consumption source, and
    # never the export credit. Detected here, before the sensors are built, because the
    # VAT sensor needs the list the moment it is created.
    detected = await async_detect_vat_sources(hass)
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"detected_vat_sources": detected}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    kinds: list[str] = hass.data[DOMAIN][entry.entry_id].get("kinds") or []
    ids = _entity_ids(hass, entry)
    pairs = [
        (ids[f"{kind}_energy"], ids[f"{kind}_cost"])
        for kind in kinds
        if f"{kind}_energy" in ids and f"{kind}_cost" in ids
    ]
    if pairs:
        await async_add_sources(hass, pairs)

    await _async_backfill_once(hass, entry, ids, detected)

    entry.async_on_unload(entry.add_update_listener(_async_reload))
    _async_register_services(hass)
    return True


async def _async_backfill_once(
    hass: HomeAssistant,
    entry: ConfigEntry,
    ids: dict[str, str],
    detected: list[str],
) -> None:
    """Rebuild the charge history, if a start date is set and we haven't already.

    Writing the same history twice is harmless -- the rows are replaced, not added to --
    but it is slow and it would fight the live sensors on every restart, so what has
    been done is remembered.
    """
    opts = {**entry.data, **entry.options}
    start_date = opts.get(CONF_START_DATE)
    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    done = await store.async_load() or {}

    if not start_date:
        # No date means no history is wanted. Forget any we wrote before, so that setting
        # a date again later actually rebuilds rather than being taken for a repeat.
        if done.pop(entry.entry_id, None) is not None:
            await store.async_save(done)
        return

    # What was backfilled depends on the date, the rates it was computed from, and the
    # version of the code that computed it -- so a rate change or an upgrade that fixes
    # the maths rewrites the history, while a plain restart does not.
    recipe = "|".join(
        str(x)
        for x in (
            integration_version(hass),
            start_date,
            opts.get(CONF_STANDING_CHARGE),
            opts.get(CONF_LEVY_AMOUNT),
            opts.get(CONF_VAT_RATE),
        )
    )
    if done.get(entry.entry_id) == recipe:
        return

    totals = await async_backfill(
        hass,
        start_date=start_date,
        currency=opts.get(CONF_CURRENCY) or DEFAULT_CURRENCY,
        standing_rate=float(opts.get(CONF_STANDING_CHARGE) or 0),
        levy_amount=float(opts.get(CONF_LEVY_AMOUNT) or 0),
        vat_rate=float(opts.get(CONF_VAT_RATE) or 0),
        vat_sources=list(opts.get(CONF_VAT_SOURCES) or detected),
        entity_ids=ids,
    )

    # Hand the sensors the total the history says they should be at. Their state is
    # their running total, so this is what keeps the live statistics continuous with
    # what was just written.
    sensors = hass.data[DOMAIN][entry.entry_id].get("cost_sensors") or {}
    for kind, total in totals.items():
        if sensor := sensors.get(kind):
            sensor.set_total(total)

    done[entry.entry_id] = recipe
    await store.async_save(done)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Clean up after ourselves: take the sources back off the Energy dashboard.

    Leaving them behind would show as broken rows pointing at entities that no longer
    exist. The registry entries are still around at this point, which is how we know
    which sources were ours.
    """
    energy_entities = [
        entity_id
        for suffix, entity_id in _entity_ids(hass, entry).items()
        if suffix.endswith("_energy")
    ]
    if energy_entities:
        await async_remove_sources(hass, energy_entities)

    store: Store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    done = await store.async_load() or {}
    if done.pop(entry.entry_id, None) is not None:
        await store.async_save(done)


async def _async_reload(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Rates changed in the options flow -- rebuild the entities.

    The running totals survive: they are restored from the entities' own stored state,
    so a rate change only ever affects what accrues from here on.
    """
    await hass.config_entries.async_reload(entry.entry_id)


def _async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_SET_TOTAL):
        return

    async def _set_total(call: ServiceCall) -> None:
        """Overwrite a charge's running total.

        Useful when seeding the integration to line up with a bill you already paid, or
        correcting a total after a period when Home Assistant was down.
        """
        value: float = call.data[ATTR_VALUE]
        targets: list[str] = call.data["entity_id"]
        found = False
        for store in hass.data.get(DOMAIN, {}).values():
            for sensor in (store.get("cost_sensors") or {}).values():
                if sensor.entity_id in targets:
                    sensor.set_total(value)
                    found = True
        if not found:
            raise ServiceValidationError(
                f"None of {', '.join(targets)} is a WattElse cost sensor"
            )

    hass.services.async_register(DOMAIN, SERVICE_SET_TOTAL, _set_total, SET_TOTAL_SCHEMA)
