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


def _new_flow(stat_energy_from: str, stat_cost: str) -> dict[str, Any]:
    """One consumption flow inside a grid source."""
    return {
        "stat_energy_from": stat_energy_from,
        "stat_cost": stat_cost,
        "entity_energy_price": None,
        "number_energy_price": None,
    }


def _new_grid_source(
    stat_energy_from: str, stat_cost: str, template: dict[str, Any] | None
) -> dict[str, Any]:
    """Build a grid source shaped like the ones this HA version already stores.

    Core has used two shapes over time: a flat one (stat_energy_from on the source)
    and a nested one (flow_from/flow_to lists). Cloning the keys of an existing grid
    source keeps us compatible with whatever this install actually uses.
    """
    if template is None or "flow_from" in template:
        return {
            "type": "grid",
            "flow_from": [_new_flow(stat_energy_from, stat_cost)],
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


def _without_ours(
    sources: list[dict[str, Any]], ours: set[str]
) -> list[dict[str, Any]]:
    """Every source with our charges taken back out, in their original order.

    Our charges can be in either of two places: a flow inside somebody else's grid
    source, which is where they are put now, or a grid source of their own, which is
    where versions up to 1.3.0 put them. Both are cleaned up. A source left holding
    nothing at all was one of ours and goes with them; one that still has an export
    flow is kept, since that is the user's.
    """
    kept: list[dict[str, Any]] = []
    for source in sources:
        if source.get("type") != "grid":
            kept.append(source)
            continue
        if "flow_from" in source:
            flows = [
                f
                for f in source.get("flow_from") or []
                if f.get("stat_energy_from") not in ours
            ]
            if not flows and not (source.get("flow_to") or []):
                continue
            kept.append({**source, "flow_from": flows})
            continue
        if not ours.intersection(_energy_stat(source)):
            kept.append(source)
    return kept


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
    """Add (energy_entity, cost_entity) pairs to the Energy dashboard, in bill order.

    The charges go *inside* an existing grid source's `flow_from`, after the tariffs
    already there -- not into grid sources of their own. That is what puts the export
    credit last: the dashboard's table walks one source at a time, drawing that source's
    consumption flows and then its return-to-grid flows, so a charge parked in a source
    of its own lands *below* the export row of the source before it, however the sources
    themselves are ordered.

    Ending up with: the user's tariffs, then the charges in `pairs` order, then the
    export credit, then the total. The tariffs keep their own relative order, and only
    our flows are ever added or moved.
    """
    manager = await _get_manager(hass)
    if manager is None or manager.data is None:
        return

    sources: list[dict[str, Any]] = list(manager.data.get("energy_sources") or [])
    ours = {energy for energy, _ in pairs}

    # Anything of ours already on the dashboard is dropped first, wherever it sits --
    # including the standalone sources older versions of this integration created, which
    # is what pushed the export credit up the list.
    kept = _without_ours(sources, ours)

    host = next(
        (s for s in kept if s.get("type") == "grid" and "flow_from" in s), None
    )
    if host is not None:
        host["flow_from"] = list(host["flow_from"]) + [
            _new_flow(energy, cost) for energy, cost in pairs
        ]
        wanted = kept
    else:
        # A legacy flat layout, or no grid source at all: fall back to one source per
        # charge, appended at the end.
        template = next((s for s in kept if s.get("type") == "grid"), None)
        wanted = kept + [
            _new_grid_source(energy, cost, template) for energy, cost in pairs
        ]

    if wanted == sources:
        return

    try:
        await manager.async_update(
            {
                "energy_sources": wanted,
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

    _LOGGER.info(
        "The Energy dashboard now lists %d charge(s), in bill order: %s",
        len(pairs),
        ", ".join(energy for energy, _ in pairs),
    )


async def async_remove_sources(hass: HomeAssistant, energy_entities: list[str]) -> None:
    """Take our charges back off the Energy dashboard, leaving the user's tariffs be."""
    manager = await _get_manager(hass)
    if manager is None or manager.data is None:
        return

    sources = list(manager.data.get("energy_sources") or [])
    kept = _without_ours(sources, set(energy_entities))
    if kept == sources:
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

    _LOGGER.info("Removed the charges from the Energy dashboard")


async def async_detect_vat_sources(hass: HomeAssistant) -> list[str]:
    """Find the cost sensors that VAT should be charged on.

    VAT is charged on what you *consume from the grid*, and on this integration's own
    fixed charges. It is NOT charged on what you export: an export credit is money
    coming back to you, and suppliers apply 0% to it. So we take every grid source's
    cost sensor and deliberately never touch `stat_energy_to` / `stat_compensation`.

    Our own phantom sources are skipped -- the standing charge and the levy feed VAT
    directly, in code, and picking them up here again would tax them twice.

    Home Assistant creates a cost sensor per priced grid source named after the energy
    statistic, so `sensor.foo` gets `sensor.foo_cost`. An explicit `stat_cost` on the
    source wins over that convention.
    """
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    from .const import DOMAIN  # noqa: PLC0415

    manager = await _get_manager(hass)
    if manager is None or manager.data is None:
        return []

    registry = er.async_get(hass)

    def is_ours(entity_id: str | None) -> bool:
        if not entity_id:
            return False
        entry = registry.async_get(entity_id)
        return entry is not None and entry.platform == DOMAIN

    found: list[str] = []
    for source in manager.data.get("energy_sources") or []:
        if source.get("type") != "grid":
            continue
        flows = (
            source.get("flow_from")
            if "flow_from" in source
            else [source] if source.get("stat_energy_from") else []
        )
        for flow in flows or []:
            energy = flow.get("stat_energy_from")
            if not energy or is_ours(energy):
                continue
            cost = flow.get("stat_cost")
            if not cost and (
                flow.get("number_energy_price") is not None
                or flow.get("entity_energy_price")
            ):
                cost = f"{energy}_cost"
            if cost and not is_ours(cost) and cost not in found:
                found.append(cost)

    _LOGGER.debug("VAT will be charged on: %s", found)
    return found
