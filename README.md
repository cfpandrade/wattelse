# WattElse

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cfpandrade&repository=wattelse&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=wattelse)
[![hacs][hacs-badge]][hacs-url]
[![release][release-badge]][release-url]

<img src="custom_components/wattelse/brand/icon.png" width="120" align="right" alt="WattElse">

**Everything on your electricity bill that isn't kilowatt-hours.**

Home Assistant's Energy dashboard can only do one thing: multiply kWh by a price. But a
real bill also has a standing charge, often a flat monthly levy, and VAT on top of all of
it. Those can easily add up to a quarter of what you actually pay — so the dashboard total
and the bill total never agree, and you're left wondering which one is lying.

WattElse models those charges as sensors and puts them on the Energy dashboard as their
own lines, so the dashboard finally adds up like the bill does.

### Before

The dashboard only knows about the energy you used.

```
Grid consumption                         ##.##
```

### After

Every line of the bill, in bill order.

```
Day Units        0.2440 /kWh             ##.##
Night Units      0.1235 /kWh             ##.##
Peak Units       0.2990 /kWh             ##.##
Levy             1.46 /month              #.##
Standing Charge  0.6798 /day             ##.##
VAT 9%                                    #.##
Return to grid                          -##.##
                                      --------
                                         ##.##
```

## How it works

The Energy dashboard will not create a source without an energy statistic. So each charge
gets a **phantom energy sensor** that is permanently 0 kWh, paired with a **cost sensor**
that carries the money. The charge shows up as a source with 0 kWh and its amount, and it
adds to the dashboard total.

WattElse registers those sources on the Energy dashboard for you when you install it, and
takes them back off when you remove it.

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

Copy `custom_components/wattelse` into your `config/custom_components/` folder and restart.

## Setup

One form. Leave a charge at `0` and it simply isn't created — a supplier with no levy
doesn't get a levy row.

| Field | What it is |
|---|---|
| **Standing charge** | The fixed daily charge, **excluding tax**. Accrues continuously. |
| **Levy** | A flat monthly fee, **excluding tax**. Defaults to Ireland's *PSO Levy*; name it whatever your bill calls it — green levy, network fee, meter rental. |
| **VAT rate** | The percentage your supplier applies. Set it to `0` if electricity isn't taxed where you are, and no VAT line is created. |
| **Apply VAT to** | Optional. Leave it empty — see below. |
| **Show rate in name** | Renders the rate into the source name, so the Sources list documents the tariff it's charging you. |

### Who gets taxed

You don't have to answer that. WattElse reads your Energy dashboard and taxes **every grid
consumption source** it finds there — day, night, peak, and anything else you've added —
along with the standing charge and the levy.

The **export credit is never taxed**. Money coming back to you isn't a purchase, and
suppliers apply 0% to it, which is why it sits *after* the VAT line on the bill.

Fill in *Apply VAT to* only if you want to override that, for instance when one of your
sources is billed tax-free.

### One thing you must do

**Set every kWh price to the rate *without* tax** in the Energy dashboard — peak, off-peak,
night, all of them.

WattElse adds the tax as its own line, exactly like your bill does. If you leave your kWh
prices tax-inclusive you'll be taxed twice. Bills quote the net rate anyway, so this
usually just means copying the number straight off the bill.

## Design notes

Two decisions that are less obvious than they look, and that you'll be glad of later.

**Charges accrue incrementally, not from a start date.** The naive way to build a standing
charge sensor is `(now - install_date) × rate`. It works right up until the day the rate
changes — and then it silently rewrites your entire history at the new rate, and every
past month stops matching the bill you actually paid. WattElse instead keeps a running
total and adds to it as time passes. Change a rate and only the future moves.

**The monthly levy is a step, not a trickle.** It's tempting to spread a monthly fee across
the days of the month. But a flat monthly fee prorated by day can never be right for both
30- and 31-day billing cycles: it overshoots on the long ones and undershoots on the short
ones, leaving a permanent drift. Suppliers date the charge at month end, so WattElse adds
the whole amount when the month rolls over. Billing cycles that run mid-month to mid-month
always contain exactly one month boundary, so they always get exactly one levy.

The same reasoning applies to VAT: it taxes each *increment* as it happens, not the running
total. If the VAT rate changes, past tax stays at the rate you were actually charged.

## About small differences

Expect the dashboard to land close to the bill, not exactly on it. Suppliers round every
line to two decimals and then add the rounded numbers up, while WattElse accumulates at
full precision — so a cent or two either way is rounding, not an error.

A bigger gap is usually one of these, and they're worth ruling out before blaming the
integration:

- **Your kWh prices still include tax.** Then it's counted twice. See above.
- **Your consumption data doesn't match what the meter recorded.** The dashboard can only
  be as accurate as the kWh feeding it. If your energy comes from a clamp meter or an
  inverter rather than from the supplier's own readings, it will drift from the billed
  figure, and no amount of correct pricing will fix that.
- **The billing period isn't what you assumed.** Bills rarely run from the 1st to the last
  day of the month. Select the exact dates printed on the bill.
- **The bill has a line WattElse doesn't model** — a discount, a credit, a one-off fee.

## Backfilling history

New sensors start at zero. If you want past periods to add up too, you have two options:

- Set a total directly with the `wattelse.set_total` service. Enough to make the current
  period correct.
- Import proper hourly statistics with
  [import_statistics](https://github.com/klausj1/homeassistant-statistics), which is what
  you'd reach for anyway if you're rebuilding consumption history from your supplier's data.

## Services

### `wattelse.set_total`

Overwrite a cost sensor's running total. Useful for seeding the integration to line up with
a bill you've already paid, or correcting a total after a spell when Home Assistant was
down.

```yaml
action: wattelse.set_total
target:
  entity_id: sensor.electricity_standing_charge_cost
data:
  value: 157.26
```

## Caveats

- **The Energy dashboard's preferences have no public API.** WattElse writes to them through
  the energy manager, defensively: if a future core release moves things around, setup still
  succeeds and it just logs a warning telling you to add the sources by hand.
- **Charges keep running while Home Assistant is down.** That's deliberate — your supplier
  doesn't stop billing you because your server rebooted — so the first tick after a restart
  settles the whole offline gap.

## Tested against

Home Assistant 2026.7. Verified end to end: install form, entities, automatic Energy
dashboard registration, options flow (rates change, running totals survive), and clean
removal.

## Licence

MIT.

[hacs-badge]: https://img.shields.io/badge/HACS-Custom-41BDF5.svg
[hacs-url]: https://github.com/hacs/integration
[release-badge]: https://img.shields.io/github/v/release/cfpandrade/wattelse
[release-url]: https://github.com/cfpandrade/wattelse/releases
