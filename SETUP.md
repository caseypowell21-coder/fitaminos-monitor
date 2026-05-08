# Setup walkthrough

Follow these once. After this, the monitor runs forever on its own.

Total time: ~20 minutes if you have GHL admin access already.

---

## Part 1 — GitHub repo

### 1a. Create the repo

1. Go to https://github.com/new.
2. **Repository name**: `fitaminos-monitor`.
3. **Visibility**:
   - **Public** if you want unlimited free GitHub Actions minutes (recommended — there are no secrets in the code, only in GitHub Secrets).
   - **Private** if you'd rather keep the code hidden. You'll consume free-tier minutes (2,000/mo on personal plan); every-15-min cadence uses ~4,300/mo, so you may incur a small overage charge (~$2-5/mo) or can drop the cadence to every 30 min.
4. Click **Create repository**.

### 1b. Push the files

From your local copy of this folder:

```bash
cd /path/to/fitaminos-monitor
git init -b main
git add .
git commit -m "Initial commit: fitaminos checkout monitor v1.0.0"
git remote add origin https://github.com/<YOUR-USERNAME>/fitaminos-monitor.git
git push -u origin main
```

If you don't have `git` set up: GitHub also supports drag-and-drop upload via the web UI. Just drag every file (including the hidden `.github` folder) into the new repo's "Add file -> Upload files" dialog.

### 1c. Add GitHub Actions secrets

Repo page → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**.

Add each of these:

| Secret name | What goes in it | Required? |
| --- | --- | --- |
| `GHL_API_KEY` | Your GoHighLevel API key (see Part 2) | Required |
| `GHL_LOCATION_ID` | Your GHL Location ID | Required |
| `ALERT_PHONE` | Phone to text — E.164 format, e.g. `+15555551234` | Required |
| `ALERT_EMAIL` | Fallback email if SMS fails | Recommended |
| `SMTP_HOST` | e.g. `smtp.gmail.com` | If using email fallback |
| `SMTP_PORT` | `587` (STARTTLS) or `465` (SSL) | If using email fallback |
| `SMTP_USER` | SMTP username | If using email fallback |
| `SMTP_PASS` | SMTP password / app password | If using email fallback |
| `SMTP_FROM` | Sender address (often same as SMTP_USER) | If using email fallback |

### 1d. (Optional) Add repo variables

Same page, switch to the **Variables** tab → **New repository variable**.

| Variable name | What it does |
| --- | --- |
| `ALERT_QUIET_HOURS` | E.g. `22:00-06:00`. SMS is suppressed in this window — alerts go to email instead. Server time is UTC, so adjust accordingly (Pacific ≈ UTC-7/-8). |
| `PRODUCT_URL` | A specific stable product URL (e.g. `https://fitaminos.com/product/your-bestseller/`). If unset, the script picks the first product on `/shop/`. |

---

## Part 2 — GoHighLevel API

### 2a. Generate an API key

1. Log into GoHighLevel (the **agency** view if you have one, or the location view).
2. **Settings** → **Business Profile**: copy your **Location ID** (also visible in the URL: `/v2/location/<LOCATION_ID>/...`). This is the value for `GHL_LOCATION_ID`.
3. Decide which key type you want:
   - **Location API key** (legacy): Settings → API Keys → Create. Quick to set up, scoped to one location. Works with the Conversations endpoint via `Authorization: Bearer <key>` and `Version: 2021-04-15`.
   - **Private Integration token** (newer, preferred): Settings → Integrations → Private Integrations → Create. Grant `conversations.write`, `conversations.readonly`, `contacts.write`, `contacts.readonly` scopes.
4. Copy the resulting token. This is the value for `GHL_API_KEY`.

> If your GHL plan uses a marketplace OAuth app instead, you'll need to mint a location-scoped access token and refresh it. For a single-account monitor, the Private Integration token is the simplest path.

### 2b. Verify the key works

Replace `<KEY>`, `<LOCATION_ID>`, `<PHONE>`:

```bash
# 1. Find or create a contact for the alert recipient
curl -X GET "https://services.leadconnectorhq.com/contacts/?locationId=<LOCATION_ID>&query=<PHONE>" \
  -H "Authorization: Bearer <KEY>" \
  -H "Version: 2021-04-15"

# 2. If no contact exists, create one
curl -X POST "https://services.leadconnectorhq.com/contacts/" \
  -H "Authorization: Bearer <KEY>" \
  -H "Version: 2021-04-15" \
  -H "Content-Type: application/json" \
  -d '{
    "locationId": "<LOCATION_ID>",
    "phone": "<PHONE>",
    "firstName": "Site",
    "lastName": "Monitor Alerts",
    "tags": ["site-monitor"]
  }'

# 3. Send a test SMS — copy the contactId from step 1 or 2 into <CONTACT_ID>
curl -X POST "https://services.leadconnectorhq.com/conversations/messages" \
  -H "Authorization: Bearer <KEY>" \
  -H "Version: 2021-04-15" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "SMS",
    "contactId": "<CONTACT_ID>",
    "locationId": "<LOCATION_ID>",
    "message": "test from fitaminos monitor"
  }'
```

If you get a 200/201 and an SMS lands on your phone within ~10 seconds, the GHL side is wired up correctly.

> **Note**: the `alerts.py` module handles the contact lookup/create cycle automatically — you don't need to do it manually before the monitor runs. The curl steps above are just for verifying the credentials work.

### 2c. Verify endpoints against current docs

GHL has two API generations:

- **HighLevel API v2** (`services.leadconnectorhq.com`) — what this script uses. Docs: https://highlevel.stoplight.io.
- **HighLevel API v1** (`rest.gohighlevel.com`) — legacy.

If GHL changes endpoint paths, you'll see HTTP 404 or 401 in the workflow logs. Update `alerts.py` accordingly. The relevant endpoints today are:
- `GET /contacts/?locationId=...&query=...`
- `POST /contacts/`
- `POST /conversations/messages`

---

## Part 3 — First test run

1. Repo page → **Actions** tab.
2. Left sidebar → **Fitaminos Checkout Monitor**.
3. Right side → **Run workflow** dropdown → **Run workflow** button.
4. Wait ~2 minutes. Refresh.

**Green check** ✅ — the monitor is live. From now on it runs automatically every 15 minutes.

**Red X** ❌ — open the failed run, expand the steps to see what broke:
- "Install Playwright Chromium" failing → transient network issue, re-run.
- "Run monitor" failing with `ALERT_PHONE not set` etc → secrets weren't saved correctly. Re-check Part 1c.
- "Run monitor" failing with a real check failure (e.g. "homepage missing 'Fitaminos' brand marker") → the site really is broken, OR a CSS selector needs updating. Download the failure artifact (top of the run page) for the screenshot + DOM excerpt + report.

### Manually trigger a "fake" failure to test alerting

Easiest test: temporarily edit `monitor.py` so the first step asserts something impossible:

```python
def step_homepage(page: Page) -> tuple[str, str]:
    ...
    _assert(False, "manual test failure")  # add this line
```

Push, run the workflow, confirm the SMS lands. Remove the line and push again.

Or, run `alerts.py` locally with the secrets exported as env vars:

```bash
export GHL_API_KEY=...
export GHL_LOCATION_ID=...
export ALERT_PHONE=+15555551234
python alerts.py "manual test from fitaminos monitor"
```

---

## Part 4 — Tuning

### Change check frequency

Edit `.github/workflows/monitor.yml`:

```yaml
on:
  schedule:
    - cron: '*/15 * * * *'   # every 15 min
    # - cron: '*/30 * * * *' # every 30 min — half the cost
    # - cron: '0 * * * *'    # hourly
```

### Add another site

Either:
- Copy this whole repo as `peptides-monitor`, change `BASE_URL` in `monitor.py`, set its own secrets, push.
- Or add a second workflow file `.github/workflows/peptides.yml` and a second monitor script `monitor_peptides.py`. The workflows run independently.

### Silence during planned maintenance

Repo → **Actions** tab → **Fitaminos Checkout Monitor** → "..." menu → **Disable workflow**. Re-enable when done. (No alerts will fire while disabled, and nothing accumulates in the queue.)

### Adjust quiet hours

Set the `ALERT_QUIET_HOURS` repo variable (Part 1d). Example value: `06:00-13:00` translates to roughly 10pm-5am Pacific in UTC. Quiet-hours alerts route to email (still loud-ish in most inboxes, but won't wake you up).

### Switch alert phone

Update the `ALERT_PHONE` secret value. No code change needed.

---

## Troubleshooting cheat sheet

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `401 Unauthorized` from GHL | Bad/expired API key | Regenerate key in GHL, update secret |
| `400` on contact create with "duplicate" | The contact exists; the script handles this. If you still see it, the lookup is failing — check GHL contact's phone formatting matches `ALERT_PHONE` exactly (E.164 with `+`) |
| Monitor passes locally, fails in Actions | Different IP geofencing, bot challenge, or User-Agent block | Check the failure DOM excerpt for Cloudflare / WAF challenge text |
| Cron not firing | GitHub disables scheduled workflows after 60 days of repo inactivity | Push any commit to wake it up; consider adding a no-op `workflow_dispatch` trigger you click weekly |
| Alerts work but stop landing | Carrier filtering of "FAIL" keyword | Edit the alert message text to be less filter-baity |
