# fitaminos-monitor

A free, GitHub-Actions-hosted synthetic monitor for **fitaminos.com**. Every 15 minutes it walks the buyer flow:

1. Homepage loads
2. /shop/ loads with products visible
3. A product can be added to cart
4. /cart/ renders the line item, totals, and checkout button
5. /checkout/ renders billing fields + payment options

It **does not** submit a payment. If any step fails, you get an SMS via GoHighLevel within ~30 seconds and a screenshot + DOM excerpt is saved as a workflow artifact.

SMS is the only channel under normal conditions; email is a fallback that fires **only** when the SMS send fails (GHL down, expired key, rate-limited, network error) — a successful SMS suppresses email so Casey never gets two pings for one failure.

## Files

| File | What it does |
| --- | --- |
| `monitor.py` | The Playwright-driven check sequence. Captures artifacts on failure, exits non-zero. v1.0.0 |
| `alerts.py` | GoHighLevel SMS sender + SMTP email fallback + optional quiet hours. |
| `requirements.txt` | Pinned dependencies (`playwright`, `requests`). |
| `.github/workflows/monitor.yml` | Runs every 15 min, uploads failure artifacts. |
| `SETUP.md` | Step-by-step setup walkthrough. **Start there.** |

## Cost

- **GitHub Actions**: free. Each run uses ~1.5 minutes of Linux time. Even at every-15-min cadence (96 runs/day) you'll consume ~144 min/day. Free tier on a personal account is 2,000 min/month — you'll burn ~4,300 min/month, so you'll need a Free or Pro plan with public repo, or pay-as-you-go (~$2-5/mo) on a private repo. Easiest workaround: keep the repo **public** (with no secrets in code — only in GitHub Secrets). Then it's truly $0.
- **GoHighLevel SMS**: uses your existing GHL plan. Each failure SMS counts as one outbound message under your account.
- **No new infra to manage.**

## Quick start

See [SETUP.md](SETUP.md). The very short version:

```bash
# 1. Create a private (or public) GitHub repo named fitaminos-monitor
# 2. Push these files to it
# 3. In repo Settings -> Secrets and variables -> Actions, add:
#    GHL_API_KEY, GHL_LOCATION_ID, ALERT_PHONE, ALERT_EMAIL
# 4. Actions tab -> "Fitaminos Checkout Monitor" -> Run workflow -> verify it goes green
# 5. Done. It will now run every 15 min automatically.
```

## Caveats

- Monitor failures during quiet hours are still real failures. Either configure quiet hours in GHL or set `ALERT_QUIET_HOURS` (e.g. `22:00-06:00`) as a repo variable — quiet hours route alerts to email instead of SMS.
- The monitor itself can fail (rare GitHub Actions outage, Playwright bug). For paranoid coverage, run the same script on a $5/mo VPS or Cloudflare Workers cron as a second source.
- Cron in GitHub Actions can drift by several minutes during peak load. If you need second-precision, GitHub isn't the right host.
- If WooCommerce templating changes, the CSS selectors in `monitor.py` may need updating — they're written defensively (multiple fallbacks per check) but plugin/theme overhauls can still break them. The failure report shows exactly which selector failed so updates are quick.

## Local testing

```bash
pip install -r requirements.txt
python -m playwright install chromium

# Dry run (no alerts) — just see if the checks pass against the live site:
python monitor.py

# Test the alerting path without running the monitor:
GHL_API_KEY=...  GHL_LOCATION_ID=...  ALERT_PHONE=+15555551234  python alerts.py "test alert"
```

## Adding more sites

To monitor `peptidesunleashed.com` too: copy the repo (or add a sibling workflow file `.github/workflows/peptides.yml`) with `BASE_URL` adjusted, push, set the same secrets. Each site = one workflow file.
