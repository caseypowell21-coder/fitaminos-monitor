# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**fitaminos-monitor** is a free, GitHub-Actions-hosted synthetic monitor for fitaminos.com. It simulates a real customer's checkout flow every 15 minutes:

1. Homepage loads → verify brand marker present
2. /shop/ loads → verify products visible
3. Add a product to cart → verify cart confirmation
4. /cart/ renders → verify line items, totals, checkout button
5. /checkout/ renders → verify billing + payment blocks (no actual payment submission)

If any step fails, an SMS alert fires via GoHighLevel within ~30 seconds, plus a screenshot, DOM excerpt, and failure report are saved as GitHub Actions artifacts.

**Key constraint:** Email is SMS-fallback only (fires only when SMS delivery fails), never both at once.

## Architecture & Design

### Two Core Modules

**monitor.py (v1.0.1)** – Playwright-driven synthetic checker
- `run_checks()`: orchestrates the 5-step sequence, capturing artifacts on first failure
- `step_*()` functions: individual checks with fallback selectors for WooCommerce/block-based variations
- Defensive CSS selector strategy: each step tries multiple selector paths (classic WC, block-based, custom) and breaks early on first match
- `dismiss_age_gate()`: handles the EMAV (Easy Modal Age Verification) overlay with dual defense — pre-seeded cookie + click-based dismissal after every navigation
- Exit codes: 0 (all pass), 1 (check failure), 2 (Playwright crash)

**alerts.py (v1.1.0)** – SMS-first, email-fallback alerting
- `send_alert()`: public entry point; routes based on quiet hours or SMS success
- `send_via_ghl()`: GoHighLevel Conversations API → SMS (primary)
  - Contact lookup by phone (E.164)
  - Auto-creates contact if missing (idempotent)
  - Handles 2xx as success (future-proof: GHL returns 200/201/202)
- `send_via_email()`: SMTP fallback (only fires when SMS fails or quiet hours active)
- Quiet hours logic: `ALERT_QUIET_HOURS` env var (e.g. "22:00-06:00") suppresses SMS, routes to email instead

### Configuration Strategy

**Hard-coded:**
- `BASE_URL = "https://fitaminos.com"` (monitor.py)
- GHL API version `2021-04-15` (alerts.py)
- 20s default timeouts, 25s navigation timeout

**Environment Variables (required):**
- `GHL_API_KEY`, `GHL_LOCATION_ID`, `ALERT_PHONE` (GitHub Secrets)
- `ALERT_EMAIL`, `SMTP_*` (Secrets, optional but recommended for email fallback)

**Repository Variables (optional):**
- `ALERT_QUIET_HOURS`: "HH:MM-HH:MM" (UTC)
- `PRODUCT_URL`: override which product to add to cart (defaults to first product on /shop/)

**GitHub Actions:**
- Secrets are injected as env vars in the `Run monitor` step
- `ARTIFACT_DIR` is set to a GitHub workspace subdirectory for artifact capture
- Cron runs every 15 min (UTC); can be adjusted in `.github/workflows/monitor.yml`

### Failure & Recovery

**On check failure:**
- Capture full-page screenshot → `failure-{step_name}.png`
- Capture first 4000 chars of DOM → embedded in failure report
- Write failure report as Markdown table → `failure-report.md`
- Write structured JSON summary → `run-summary.json`
- Send alert via GHL SMS (or email if quiet hours / SMS fails)
- Exit code 1 → GitHub Actions marks workflow red

**Artifacts uploaded:**
- Screenshots, failure report, JSON summary (retention: 7 days on failure, 3 days always)
- Manual debugging: download from Actions tab, inspect selectors and timing

### Known Gotchas & Design Decisions

1. **EMAV age-gate**: Pre-seeded cookie (`emav-age-verified=1`) + click-based dismissal. If the cookie name changes, the click fallback catches it. Both are non-fatal — a failed dismissal doesn't fail the step.

2. **Floating add-to-cart button**: Fitaminos theme has a sticky button that's `display:none` until scroll. Explicitly excluded via `:not(.floating_add_to_cart_button)` selector to avoid Playwright's visibility check looping forever.

3. **Email is fallback-only**: Changed in v1.1.0. Previously both SMS and email fired on every alert. Now: SMS succeeds → email suppressed. SMS fails (4xx/5xx, timeout, missing creds) → email fires. Quiet hours → email only (SMS not attempted).

4. **Contact auto-creation**: alerts.py automatically creates a "Site Monitor Alerts" contact if the phone doesn't exist in GHL. Idempotent: duplicate errors are caught and re-lookup is attempted.

5. **PRODUCT_URL defaults carefully**: GitHub Actions expands unset repo vars to `""` (empty string), not "unset". So `PRODUCT_URL` uses `os.environ.get(...) or default` instead of `.get(..., default)` to correctly fall back to /shop/.

6. **Timeout hierarchy**: 
   - Default (page actions): 20s
   - Navigation (page.goto): 25s
   - Individual waits (e.g., EMAV dismiss): 5s

## Development & Testing

### Local Setup

```bash
# Install dependencies
pip install -r requirements.txt
python -m playwright install chromium

# Dry run against live site (no alerts)
python monitor.py

# Test alerting without monitor
export GHL_API_KEY=...
export GHL_LOCATION_ID=...
export ALERT_PHONE=+15555551234
python alerts.py "test message"
```

### Testing Patterns

**Test a single step in isolation:**
- Create a minimal script that calls `step_homepage(page)`, `step_shop(page)`, etc.
- Useful for debugging CSS selectors after WooCommerce theme updates

**Fake a failure to test alerts:**
- Temporarily add `_assert(False, "test failure")` at the top of a step
- Push, run workflow, verify SMS/email lands
- Remove and push again

**Validate GHL credentials before deploying:**
- Run `python alerts.py "test alert"` locally with secrets exported
- Confirm SMS lands within ~10s
- Check contact was created/found (look in GHL UI)

**Test email fallback:**
- Set valid SMTP_* secrets but invalid GHL_API_KEY
- Run `python monitor.py` and force a failure
- Verify email fires with "[SMS DELIVERY FAILED]" prefix

### Adding a Second Site

To monitor `peptidesunleashed.com`:
- **Option 1:** Copy the entire repo as `peptides-monitor`, change `BASE_URL` in monitor.py, set separate secrets
- **Option 2:** Add `.github/workflows/peptides.yml` + `monitor_peptides.py` to the same repo; workflows run independently

Either approach is fine; Option 1 (separate repo) keeps secrets isolated.

## Common Changes

### Update CSS Selectors
- WooCommerce plugin updates or theme changes can break selectors
- Failure report shows which selector failed + full DOM excerpt (first 4000 chars)
- Add new fallback selectors to the try-multiple-paths lists in each step (see `step_shop()` example)
- Test locally before pushing: `python monitor.py` should pass

### Change Check Frequency
- Edit `.github/workflows/monitor.yml` → `on.schedule.cron`
- Every 15 min: `*/15 * * * *` (96 runs/day, ~144 min/day)
- Every 30 min: `*/30 * * * *` (cuts cost in half)

### Adjust Quiet Hours
- Set repo variable `ALERT_QUIET_HOURS`, e.g. `22:00-06:00` (UTC)
- Quiet-hours failures email instead of SMS (can review in the morning)
- Server time is UTC; adjust accordingly (Pacific ≈ UTC-7/-8)

### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `401 Unauthorized` from GHL | Expired/bad API key | Regenerate in GHL, update secret |
| `400 "duplicate"` on contact create | Contact exists but lookup failed | Check phone formatting matches exactly (E.164 with `+`) |
| Monitor passes locally, fails in Actions | Geofencing, bot challenge, WAF | Check failure DOM for Cloudflare/WAF text; may need User-Agent or IP allowlist |
| Cron doesn't fire | Scheduled workflows disabled after 60 days inactivity | Push a commit to wake it up; add `workflow_dispatch` trigger |
| Alerts work but stop landing | Carrier SMS filtering | Edit alert text to avoid filter-baity keywords |

## Dependencies

- **playwright==1.48.0** – headless browser automation (Chromium)
- **requests==2.32.3** – HTTP client (GHL API, SMTP not used)
- **Python 3.11+** – required (uses `|` union syntax)

## Exit Codes

- **0** – All checks passed
- **1** – A check failed; alert was sent (or attempted)
- **2** – Playwright crash at startup (catastrophic); alert still attempted

## Files

- `monitor.py` – Main synthetic check sequence
- `alerts.py` – GoHighLevel SMS + SMTP email fallback
- `requirements.txt` – Pinned dependencies
- `.github/workflows/monitor.yml` – GitHub Actions workflow (every 15 min)
- `SETUP.md` – Step-by-step setup walkthrough (start here for first-time users)
- `README.md` – High-level overview + cost breakdown
