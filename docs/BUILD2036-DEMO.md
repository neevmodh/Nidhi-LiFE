# BUILD 2036 demo script (2 to 3 minutes)

The story: **from the meter to the mission.** Measure, act, prove. Everything shown runs; the meter is simulated and labelled as such until a real one is linked.

## Before you start

1. Run the API, web and app locally (see the README, "Run it locally"). Use a fresh database so the numbers are clean.
2. Create a DISCOM engineer: `python -m app.create_admin --email <email> --name "UGVCL Engineer" --role discom_engineer --discom ugvcl` (it asks for a password).
3. In the app, sign up five households in one district, put them in one society (the society view stays hidden below five meters), and give two of them rooftop solar in onboarding.
4. Open Live energy once on each home so every meter exists.
5. On one home, add a bill reading of about double its usual units (Progress, add a month), so the bill-vs-meter check has something to flag.

Two browser windows: the app (household) and `/discom` (utility, signed in as the engineer).

## The script

| Time | Say | Show |
|---|---|---|
| 0:00 | "Nidhi turns a bill photo into a plan. For BUILD 2036 we connected it to the meter itself." | App home, then Me, then **Live energy**. |
| 0:15 | "This is the home's smart meter right now: power in use, from the panels, from the grid, and the last 24 hours. The badge says simulated, because no real meter is linked, and we never hide that." | Point at the **Simulated meter** badge and the chart with the sun hours and the evening peak shaded. |
| 0:40 | "I just ran the geyser. I tell the meter, and the reading changes." | Tap **Geyser** under "I just ran…". The load jumps. |
| 0:55 | "The energy agent reads the meter, prices the slab and ranks what to do by rupees, then CO₂. Every number is computed in code. AI can only reword the summary, and the server throws the text away if it contains a number it wasn't given." | Open **Energy agent**: summary, ranked actions, the five steps. |
| 1:20 | "And this action can be proved by the meter itself." | Tap **Confirm with my meter**. The celebration shows points with no photo. |
| 1:35 | "The bill comes from the meter's own readings, with the exact slab split and the net-metering credit. If it disagrees with the scanned bill, we write the letter to the DISCOM." | **Bill from your meter**, scroll to the mismatch and the letter. |
| 1:55 | "Neighbours see only totals, and only once five homes have meters, so no home can be picked out." | **Society energy**. |
| 2:10 | "Now the utility. Same data, by feeder." | Switch to `/discom`: overview, **Feeders** (utilisation, peak above the 90th percentile). |
| 2:25 | "The flagged bill shows up as an anomaly, by meter number, never a name. The engineer plans an outage and every household on that feeder is notified." | **Anomalies**, then **Outages**: plan one; switch back to the app and show the banner on Live energy. |
| 2:45 | "Same stack, no new infrastructure, 399 backend tests on SQLite and PostgreSQL, in English, Gujarati and Hindi. Nidhi: from the meter to the mission." | Back to the cover slide. |

## If something goes wrong

- **Live energy is empty:** finish onboarding for that home first; the meter needs a household.
- **Confirm says the meter doesn't show a heavy load yet:** tap an appliance under "I just ran…" first. It also refuses during the 6 to 10 PM evening peak, by design.
- **The society view is hidden:** it needs five homes with meters.
- **No flag in the console:** open Bill from your meter on the home with the mismatching reading once; that raises it.

## Questions to expect

- *Is the meter data real?* No. It is simulated, calibrated to the household's stated usage, and labelled everywhere. A real meter posts HMAC-signed readings to the same endpoint, and the simulated history is dropped when one is linked.
- *Can the AI make up numbers?* No. The summary is accepted only if every number in it is one the agent gave it; otherwise a plain template is shown.
- *What can the meter prove?* Today, one action: a heavy load run outside the evening peak. A whole-home reading can't prove an AC set point.
- *Where are the gaps?* No real head-end integration yet, and feeder ratings come from sanctioned loads rather than the utility's asset register. Both are in the README's limitations.
