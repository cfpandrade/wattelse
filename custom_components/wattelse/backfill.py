"""Rebuild the charges for the time before WattElse existed.

New sensors start at zero, so the Energy dashboard has nothing to show for last
month's bill -- which is usually the bill you wanted to check. If you tell WattElse
when your tariff started, it writes the hourly statistics for the whole stretch
between then and now: the standing charge hour by hour, the levy as a step at each
month boundary, and the VAT worked out from the consumption you actually recorded.

The live sensors are then set to the total they would have reached, so the running
statistics carry straight on from the history with no jump.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import logging

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_import_statistics,
    statistics_during_period,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import KIND_LEVY, KIND_STANDING, KIND_VAT

_LOGGER = logging.getLogger(__name__)


def _hours(start: datetime, end: datetime) -> list[datetime]:
    out: list[datetime] = []
    cursor = start
    while cursor <= end:
        out.append(cursor)
        cursor += timedelta(hours=1)
    return out


async def _consumption_per_hour(
    hass: HomeAssistant, stat_ids: list[str], start: datetime, end: datetime
) -> dict[datetime, float]:
    """What the grid consumption cost, hour by hour, according to the recorder.

    This is what VAT is charged on, so it has to come from the same statistics the
    Energy dashboard is drawing -- not from a re-derivation of price x kWh, which
    would quietly disagree with it.
    """
    if not stat_ids:
        return {}

    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start - timedelta(hours=1),
        end + timedelta(hours=1),
        set(stat_ids),
        "hour",
        None,
        {"sum"},
    )

    per_hour: dict[datetime, float] = {}
    for rows in stats.values():
        # Statistics carry a cumulative sum, so an hour's cost is the step between
        # one row and the one before it.
        previous: float | None = None
        for row in rows:
            total = row.get("sum")
            if total is None:
                continue
            if previous is not None:
                when = dt_util.utc_from_timestamp(row["start"] / 1000)
                per_hour[when] = per_hour.get(when, 0.0) + (total - previous)
            previous = total
    return per_hour


def _import(
    hass: HomeAssistant, statistic_id: str, unit: str, rows: list[tuple[datetime, float]]
) -> None:
    """Write a cumulative series into the recorder under an entity's own id.

    Both `sum` and `state` are written. The state matters: for a total sensor the
    recorder works out the next hour's sum as `previous sum + (new state - old
    state)`, and our sensors' state *is* their running total. Line the two up and the
    live statistics continue from the history seamlessly. Omit the state and the very
    next compile writes a step the size of the entire backfill.
    """
    metadata = StatisticMetaData(
        has_mean=False,
        has_sum=True,
        name=None,
        source="recorder",
        statistic_id=statistic_id,
        unit_of_measurement=unit,
    )
    stats = [
        StatisticData(start=when, sum=round(total, 6), state=round(total, 6))
        for when, total in rows
    ]
    async_import_statistics(hass, metadata, stats)


async def async_backfill(
    hass: HomeAssistant,
    start_date: str,
    currency: str,
    standing_rate: float,
    levy_amount: float,
    vat_rate: float,
    vat_sources: list[str],
    entity_ids: dict[str, str],
) -> dict[str, float]:
    """Write the charge history from `start_date` up to the current hour.

    Returns the total each cost sensor should now be sitting at, so the caller can
    hand it to the live sensors.
    """
    parsed = dt_util.parse_date(start_date)
    if parsed is None:
        _LOGGER.warning("Could not read the start date %s -- skipping backfill", start_date)
        return {}

    start = dt_util.start_of_local_day(parsed)
    end = dt_util.now().replace(minute=0, second=0, microsecond=0)
    if start >= end:
        return {}

    consumption = await _consumption_per_hour(hass, vat_sources, start, end)

    standing_per_hour = standing_rate / 24
    totals = {KIND_STANDING: 0.0, KIND_LEVY: 0.0, KIND_VAT: 0.0}
    series: dict[str, list[tuple[datetime, float]]] = {k: [] for k in totals}

    for hour in _hours(start, end):
        local = dt_util.as_local(hour)
        # The levy is a step, never a trickle: suppliers charge the whole month's fee at
        # the month end, and a fee prorated by day can't be right for both 30- and
        # 31-day cycles. A mid-month billing period contains exactly one boundary, so
        # it collects exactly one levy.
        levy_now = levy_amount if (local.day == 1 and local.hour == 0) else 0.0
        net = standing_per_hour + levy_now + consumption.get(dt_util.as_utc(hour), 0.0)

        totals[KIND_STANDING] += standing_per_hour
        totals[KIND_LEVY] += levy_now
        totals[KIND_VAT] += net * vat_rate / 100

        for kind in totals:
            series[kind].append((hour, totals[kind]))

    wanted = {
        KIND_STANDING: standing_rate > 0,
        KIND_LEVY: levy_amount > 0,
        KIND_VAT: vat_rate > 0,
    }
    for kind, rows in series.items():
        if not wanted[kind]:
            continue
        cost_id = entity_ids.get(f"{kind}_cost")
        energy_id = entity_ids.get(f"{kind}_energy")
        if cost_id:
            _import(hass, cost_id, currency, rows)
        if energy_id:
            # The dashboard won't draw a source whose energy statistic has no history,
            # so the phantom sensor gets its flat 0 kWh written across the same span.
            _import(
                hass,
                energy_id,
                UnitOfEnergy.KILO_WATT_HOUR,
                [(when, 0.0) for when, _ in rows],
            )

    _LOGGER.info(
        "Backfilled charges from %s: %s",
        start_date,
        ", ".join(f"{k}={v:.2f} {currency}" for k, v in totals.items() if wanted[k]),
    )
    return {kind: total for kind, total in totals.items() if wanted[kind]}
