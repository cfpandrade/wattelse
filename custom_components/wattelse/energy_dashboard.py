"""Register this integration's charges as grid sources on the Energy dashboard.

Home Assistant's Energy dashboard can only multiply kWh by a price: it has no concept
of a fixed charge or of VAT. The trick used here is to register each charge as a grid
source whose *energy* sensor is permanently 0 kWh and whose *cost* comes from our own
sensor. The charge then shows up as its own line in "Sources", with 0 kWh and its
amount, and it adds to the dashboard total -- so the dashboard reproduces the bill.

The Energy dashboard preferences are managed by `homeassistant.components.energy`.
There is no stable public API to edit them from another integration, so we go through
the energy manager and degrade gracefully (log + let the user do it by hand) if a
future core release moves things around.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def _get_manager(hass: HomeAssistant) -> Any | None:
    try:
        from homeassistant.components.energy.data import (  # noqa: PLC0415
            async_get_manager,
        )
    except ImportError:  # pragma: no cover - energy is a default integration
        _LOGGER.warning(
            "The 'energy' integration is not available; add the charges to the "
            "Energy dashboard manually"
        )
        return None
    return await async_get_manager(hass)


def _new_grid_source(
    stat_energy_from: str, stat_cost: str, template: dict[str, Any] | None
) -> dict[str, Any]:
    """Build a grid source shaped like the ones this HA version already stores.

    Core has used two shapes over time: a flat one (stat_energy_from on the source)
    and a nested one (flow_from/flow_to lists). Cloning the keys of an existing grid
    source keeps us compatible with whatever this install actually uses.
    """
    if template and "flow_from" in template:
        return {
            "type": "grid",
            "flow_from": [
                {
                    "stat_energy_from": stat_energy_from,
                    "stat_cost": stat_cost,
                    "entity_energy_price": None,
                    "number_energy_price": None,
                }
            ],
            "flow_to": [],
            "cost_adjustment_day": 0.0,
        }

    source: dict[str, Any] = {
        "type": "grid",
        "stat_energy_from": stat_energy_from,
        "stat_energy_to": None,
        "stat_cost": stat_cost,
        "stat_compensation": None,
        "entity_energy_price": None,
        "number_energy_price": None,
        "entity_energy_price_export": None,
        "number_energy_price_export": None,
        "cost_adjustment_day": 0.0,
    }
    return source


def _energy_stat(source: dict[str, Any]) -> list[str]:
    """Return the energy statistic ids a grid source consumes from."""
    if "flow_from" in source:
        return [f["stat_energy_from"] for f in source.get("flow_from") or []]
    if source.get("stat_energy_from"):
        return [source["stat_energy_from"]]
    return []


async def async_add_sources(
    hass: HomeAssistant, pairs: list[tuple[str, str]]
) -> None:
    """Add (energy_entity, cost_entity) pairs to the Energy dashboard as grid sources.

    Charges are appended at the end so they read in bill order: consumption first,
    then the fixed charges, then VAT. Existing sources are never modified.
    """
    manager = await _get_manager(hass)
    if manager is None or manager.data is None:
        return

    sources: list[dict[str, Any]] = list(manager.data.get("energy_sources") or [])
    grid_template = next((s for s in sources if s.get("type") == "grid"), None)

    known: set[str] = set()
    for source in sources:
        if source.get("type") == "grid":
            known.update(_energy_stat(source))

    added = [
        _new_grid_source(energy, cost, grid_template)
        for energy, cost in pairs
        if energy not in known
    ]
    if not added:
        return

    try:
        await manager.async_update(
            {
                "energy_sources": sources + added,
                "device_consumption": list(manager.data.get("device_consumption") or []),
            }
        )
    except Exception:  # noqa: BLE001 - never break setup over the dashboard
        _LOGGER.exception(
            "Could not add the charges to the Energy dashboard. Add them by hand: "
            "Settings > Dashboards > Energy > Add consumption, picking %s and using "
            "its matching cost sensor",
            ", ".join(e for e, _ in pairs),
        )
        return

    _LOGGER.info("Added %d charge(s) to the Energy dashboard", len(added))


async def async_remove_sources(hass: HomeAssistant, energy_entities: list[str]) -> None:
    """Remove our grid sources from the Energy dashboard again."""
    manager = await _get_manager(hass)
    if manager is None or manager.data is None:
        return

    ours = set(energy_entities)
    sources = list(manager.data.get("energy_sources") or [])
    kept = [
        s
        for s in sources
        if not (s.get("type") == "grid" and ours.intersection(_energy_stat(s)))
    ]
    if len(kept) == len(sources):
        return

    try:
        await manager.async_update(
            {
                "energy_sources": kept,
                "device_consumption": list(manager.data.get("device_consumption") or []),
            }
        )
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Could not remove the charges from the Energy dashboard")
        return

    _LOGGER.info("Removed %d charge(s) from the Energy dashboard", len(sources) - len(kept))
