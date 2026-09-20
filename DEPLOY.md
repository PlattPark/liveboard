# Computa v2 — deploy notes (Sept 20 2026)

What landed in this commit: `square.py`, `spothopper.py`, `briefs.py`, `events.py`, `mailer.py`, `events.json`,
and a `computa.py` that uses them. Nothing switches on until its secret exists — with no secrets added,
Computa behaves exactly as before.

## Secrets to add (repo → Settings → Secrets and variables → Actions)

| secret | turns on | where to get it |
|---|---|---|
| `SQUARE_ACCESS_TOKEN` | "86 kettle chips" → sold out at the register, gatesdeli.com and DoorDash; "wings are back"; sales numbers in the briefs | developer.squareup.com → your app → Production → Access token. Needs Catalog read/write + Orders read. |
| `SPOTHOPPER_EMAIL` / `SPOTHOPPER_PASSWORD` | every beers.json change mirrored to the plattparkbrewing.com beer list (86 = out of stock on the site) | the SpotHopper owner login. Their internal API — if it ever stops working Computa says so in #bar-only. |
| `MAIL_USER` / `MAIL_PASS` | email copies of the 10:30 brief and the Sunday outlook | a Workspace address + a Google app password (Account → Security → App passwords) |
| `PRESHIFT_MAIL_TO` | who gets the pre-shift email (Victor) | `victor@..., christian@...` |
| `OUTLOOK_MAIL_TO` | who gets the Sunday outlook email | `colby@..., greg@...` |

Then update `.github/workflows/computa.yml` (see `computa.yml.new` below — the env block gains the seven
lines and `events.json` joins the persist list) and cancel-and-rerun the Computa chain once
(Actions → Computa → the in-progress run → Cancel; then Run workflow). The new code lands at the next
run start.

## Prove it
1. In #bar-only: `86 kettle chips` → Computa replies "marked sold out at the register, gatesdeli.com and DoorDash".
   Check DoorDash within a few minutes. Then `kettle chips are back`.
2. `86 wings` → it asks which one; `86 all wings` does every wing item.
3. `status` → now ends with what's sold out at the register.
4. Change a price in Slack (`nadare is now $8`) → plattparkbrewing.com beer list shows $8 within ~2 minutes.
   (First sync also corrects Chela Morena on the site: it was $4.50/$7.00, beers.json says $4.75/$7.50.)
5. Tomorrow 10:30 MT: pre-shift brief in #bar-only. Sunday 4pm: week-ahead in #brew-x-bar.
   Dry-run either one from a checkout: `python3 briefs.py preshift` / `python3 briefs.py outlook`.

## What each file does
- `square.py` — catalog search + the per-location sold-out flag (the same one the POS "Mark sold out" sets);
  `day_sales()` for the briefs. `python3 square.py find "wings"` shows what would match.
- `spothopper.py` — reads the site's Beer menu, diffs it against beers.json, PUT/POSTs the difference.
  Only touches menu 50820 / section 218487. Rows like "Crowlers & 4-packs to go" are never touched.
- `briefs.py` — the two scheduled posts. Dedupes against channel history, so restarts can't double-post.
- `events.py` / `events.json` — Broncos schedule from ESPN (auto), `weekly` programming and `extra` one-offs (edit by hand).
- `mailer.py` — plain-text email copies. Off without MAIL_USER/MAIL_PASS.

## Still to do (not in this drop)
- site.json / Also Pouring panel editable from Slack (board work).
- Beer alerts (double opt-in, Google Sheet) — needs the Apps Script on your Google side.
- Delete the stray `computa.yml` at the repo root (harmless).
