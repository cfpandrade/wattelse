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
| **Charges start on** | Optional. The day your tariff started — WattElse rebuilds the history from there. See below. |

> [!IMPORTANT]
> Three things decide whether the dashboard ends up matching your bill:
>
> 1. **Every kWh price must be entered without VAT** — peak, off-peak, night, all of them.
>    WattElse adds the tax as its own line, so a tax-inclusive price is taxed twice.
> 2. **Set _Charges start on_** to the day your tariff began, or the charges start at zero
>    today and no past billing period will add up.
> 3. **The export credit is never taxed**, and you don't have to configure that.

### Who gets taxed

You don't have to answer that. WattElse reads your Energy dashboard and taxes **every grid
consumption source** it finds there — day, night, peak, and anything else you've added —
along with the standing charge and the levy.

The **export credit is never taxed**. Money coming back to you isn't a purchase, and
suppliers apply 0% to it, which is why it sits *after* the VAT line on the bill.

Fill in *Apply VAT to* only if you want to override that, for instance when one of your
sources is billed tax-free.

What it taxes is the *net* price, which is why every kWh price has to be entered without
VAT. Bills quote the net rate anyway, so that usually just means copying the number
straight off the bill — and if you leave the price tax-inclusive, the tax is counted
twice.

## Design notes

Three decisions that are less obvious than they look, and that you'll be glad of later.

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

**Backfilled statistics carry a state, not just a sum.** For a `total` sensor the recorder
works out each new hour as `previous sum + (new state − old state)`, and these sensors'
state *is* their running total. Import only the sums and the very first compile after a
restart writes a single step the size of the entire backfill — a spike in the middle of
your dashboard. Writing both lines the history up with the live sensor, so no manual sum
adjustment is ever needed.

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
- **You never set a start date.** The charges then begin at zero on the day you installed
  the integration, so any period before that is missing its standing charge, levy and VAT.
- **The bill has a line WattElse doesn't model** — a discount, a credit, a one-off fee.

## Backfilling history

New sensors start at zero, so the month you actually wanted to check — last month's bill —
has nothing to show. Fill in **Charges start on** with the day your tariff began and
WattElse writes the hourly statistics for the whole stretch between then and now:

- the **standing charge**, hour by hour;
- the **levy**, as a step at each month boundary;
- the **VAT**, worked out from the consumption cost already in your database, so it agrees
  with the same statistics the Energy dashboard is drawing rather than a re-derivation of
  its own.

The live sensors are then set to the total the history says they reached, so the running
statistics carry straight on with no jump. It runs once — change the date to run it again.

Two caveats. Your **consumption statistics have to reach back that far**, since the VAT is
computed from them; if your history starts in March, don't ask for January. And your **kWh
prices must have been the net ones all along** — WattElse taxes what the recorder stored,
so a period recorded at tax-inclusive prices gets taxed on top.

If you need finer control — a rate that changed mid-history, say — import the statistics
yourself with [import_statistics](https://github.com/klausj1/homeassistant-statistics), or
set a total directly with the `wattelse.set_total` service.

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
