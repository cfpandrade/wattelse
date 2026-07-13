# WattElse

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cfpandrade&repository=wattelse&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wattelse)
[![hacs][hacs-badge]][hacs-url]
[![release][release-badge]][release-url]

<img src="custom_components/wattelse/brand/icon.png" width="120" align="right" alt="WattElse">

**Everything on your electricity bill that isn't kilowatt-hours.**

Home Assistant's Energy dashboard can only do one thing: multiply kWh by a price. But a
real bill also has a standing charge, often a flat monthly levy, and VAT on top of all
of it. On a typical Irish bill those come to around **a quarter of what you actually
pay** — so the dashboard total and the bill total never agree, and you're left wondering
which one is lying.

WattElse models those charges as sensors and puts them on the Energy dashboard as their
own lines, so the dashboard finally adds up to the bill.

### Before

```
Grid consumption                       72.83 €
```

### After

```
Day Units      0.244 EUR/kWh           44.20 €
Night Units    0.1235 EUR/kWh          33.03 €
Peak Units     0.299 EUR/kWh            4.92 €
PSO Levy       1.46 EUR/month           1.46 €
Standing Charge 0.6798 EUR/day         21.07 €
VAT 9%                                  9.42 €
Return to grid                        -16.72 €
                                     ---------
                                       97.39 €     <- the bill said 97.38 €
```

## How it works

The Energy dashboard will not create a source without an energy statistic. So each
charge gets a **phantom energy sensor** that is permanently 0 kWh, paired with a **cost
sensor** that carries the money. The charge shows up as a source with 0 kWh and its
amount, and it adds to the dashboard total.

WattElse registers those sources on the Energy dashboard for you when you install it,
and takes them back off when you remove it.

## Install

### HACS (one click)

Click the **Open in HACS** badge at the top. It drops you straight on this repository
inside your own Home Assistant, ready to install. Then restart Home Assistant and click
the **Add integration** badge.

### HACS (by hand)

HACS → three dots → *Custom repositories* → paste
`https://github.com/cfpandrade/wattelse`, category **Integration** → Install → restart →
**Settings → Devices & Services → Add Integration → WattElse**.

### Manual

Copy `custom_components/wattelse` into your `config/custom_components/` folder and
restart.

## Setup

One form. Leave a charge at `0` and it simply isn't created — a supplier with no levy
doesn't get a levy row.

| Field | What it is |
|---|---|
| **Standing charge** | The fixed daily charge, **excluding VAT**. Accrues continuously. |
| **Levy** | A flat monthly fee (Ireland's PSO levy, for example), **excluding VAT**. Name it whatever your bill calls it. |
| **VAT rate** | The percentage. |
| **Apply VAT to** | Your grid consumption cost sensors. The standing charge and the levy are taxed automatically — don't list them here. |
| **Show rate in name** | Renders the rate into the source name, so the Sources list documents the tariff it's charging you. |

### One thing you must do

**Set your kWh prices to the rate *without* VAT** in the Energy dashboard.

WattElse adds the tax as its own line, exactly like your bill does. If you leave your
kWh prices VAT-inclusive you'll be taxed twice. Bills quote the net rate anyway, so this
usually means copying the number straight off the bill.

## Design notes

Two decisions that are less obvious than they look, and that you'll be glad of later.

**Charges accrue incrementally, not from a start date.** The naive way to build a
standing charge sensor is `(now - install_date) × rate`. It works right up until the day
the rate changes — and then it silently rewrites your entire history at the new rate,
and every past month stops matching the bill you actually paid. WattElse instead keeps a
running total and adds to it as time passes. Change a rate and only the future moves.

**The monthly levy is a step, not a trickle.** It's tempting to spread €1.46/month across
the days of the month. But a flat monthly fee prorated by day can never be right for both
30- and 31-day billing cycles: it overshoots on the long ones and undershoots on the
short ones, and you're left with a few cents of permanent drift. Suppliers date the
charge at month end, so WattElse adds the whole amount when the month rolls over. Billing
cycles that run mid-month to mid-month (the 22nd to the 21st, say) always contain exactly
one month boundary, so they always get exactly one levy. Exact, every cycle.

The same reasoning applies to VAT: it taxes each *increment* as it happens, not the
running total. If VAT changes, past tax stays at the rate you were actually charged.

## Backfilling history

New sensors start at zero. If you want your past months to add up too, you have two
options:

- Set a total directly with the `wattelse.set_total` service. Good enough to make
  "this month" correct.
- Import proper hourly statistics with
  [import_statistics](https://github.com/klausj1/homeassistant-statistics), which is what
  you'd use anyway if you're rebuilding consumption history from your supplier's data.

## Services

### `wattelse.set_total`

Overwrite a cost sensor's running total. Useful for seeding the integration to line up
with a bill you've already paid, or correcting a total after a spell when Home Assistant
was down.

```yaml
action: wattelse.set_total
target:
  entity_id: sensor.electricity_standing_charge_cost
data:
  value: 157.26
```

## Caveats

- **The Energy dashboard's preferences have no public API.** WattElse writes to them
  through the energy manager, defensively: if a future core release moves things around,
  setup still succeeds and it just logs a warning telling you to add the sources by hand.
- **Charges keep running while Home Assistant is down.** That's deliberate — your
  supplier doesn't stop billing you because your server rebooted — so the first tick
  after a restart settles the whole offline gap.

## Licence

MIT.

## Tested against

Home Assistant 2026.7. Verified end to end: install form, entities, automatic Energy
dashboard registration, options flow (rates change, running totals survive), and clean
removal.

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/cfpandrade/wattelse
[release-url]: https://github.com/cfpandrade/wattelse/releases
