"""
alerts.py v1.0.0
Alerting module for fitaminos checkout monitor.

Primary path: GoHighLevel Conversations API (SMS).
Fallback path: SMTP email.
Optional: ALERT_QUIET_HOURS gate, e.g. "22:00-06:00" — suppresses SMS during
that window but still sends email so you can review in the morning.

All credentials come from env vars. NEVER hard-code secrets here.
"""

from __future__ import annotations

import os
import sys
import smtplib
import ssl
import json
from datetime import datetime, time, timezone
from email.message import EmailMessage
from typing import Optional

import requests


GHL_BASE = "https://services.leadconnectorhq.com"
GHL_API_VERSION = "2021-04-15"  # required by GHL Conversations endpoints
HTTP_TIMEOUT = 15  # seconds


# ---------------------------------------------------------------------------
# Quiet hours
# ---------------------------------------------------------------------------

def _parse_quiet_hours(spec: str) -> Optional[tuple[time, time]]:
    """Parse 'HH:MM-HH:MM' (24h, local server time) -> (start, end)."""
    if not spec:
        return None
    try:
        start_s, end_s = spec.split("-", 1)
        start = datetime.strptime(start_s.strip(), "%H:%M").time()
        end = datetime.strptime(end_s.strip(), "%H:%M").time()
        return start, end
    except Exception:
        print(f"(alerts) ALERT_QUIET_HOURS unparseable: {spec!r} — ignoring")
        return None


def _in_quiet_hours(now: datetime, start: time, end: time) -> bool:
    """True if `now`'s time-of-day falls inside [start, end), wrapping past midnight."""
    t = now.time()
    if start <= end:
        return start <= t < end
    # wrap, e.g. 22:00-06:00
    return t >= start or t < end


# ---------------------------------------------------------------------------
# GoHighLevel SMS
# ---------------------------------------------------------------------------

def _ghl_find_contact_id(api_key: str, location_id: str, phone: str) -> Optional[str]:
    """
    Look up a contact by phone in the given location. Returns contactId or None.
    Uses GHL's Contacts search endpoint.
    """
    url = f"{GHL_BASE}/contacts/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": GHL_API_VERSION,
        "Accept": "application/json",
    }
    params = {"locationId": location_id, "query": phone, "limit": 5}
    resp = requests.get(url, headers=headers, params=params, timeout=HTTP_TIMEOUT)
    if resp.status_code != 200:
        print(f"(alerts) GHL contact search HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    data = resp.json() or {}
    contacts = data.get("contacts") or []
    for c in contacts:
        # Match on phone field; GHL stores in E.164.
        if c.get("phone") and c["phone"].replace(" ", "") == phone.replace(" ", ""):
            return c.get("id")
    return None


def _ghl_create_contact(api_key: str, location_id: str, phone: str) -> Optional[str]:
    """
    Create a 'Site Monitor Alerts' contact for this phone if it doesn't exist.
    Returns the new contactId on success, or None on failure.
    """
    url = f"{GHL_BASE}/contacts/"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
    }
    payload = {
        "locationId": location_id,
        "phone": phone,
        "firstName": "Site",
        "lastName": "Monitor Alerts",
        "tags": ["site-monitor", "fitaminos-monitor"],
        "source": "fitaminos-monitor",
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=HTTP_TIMEOUT)
    if resp.status_code in (200, 201):
        data = resp.json() or {}
        contact = data.get("contact") or data
        return contact.get("id")
    # 400 with "duplicate" means it already exists — try lookup again.
    if resp.status_code == 400 and "duplicate" in resp.text.lower():
        return _ghl_find_contact_id(api_key, location_id, phone)
    print(f"(alerts) GHL contact create HTTP {resp.status_code}: {resp.text[:300]}")
    return None


def _ghl_send_sms(
    api_key: str,
    location_id: str,
    contact_id: str,
    message: str,
) -> bool:
    """Send an SMS via the Conversations Messages endpoint."""
    url = f"{GHL_BASE}/conversations/messages"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Version": GHL_API_VERSION,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    payload = {
        "type": "SMS",
        "contactId": contact_id,
        "message": message,
        "locationId": location_id,
    }
    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=HTTP_TIMEOUT)
    if resp.status_code in (200, 201, 202):
        return True
    print(f"(alerts) GHL send SMS HTTP {resp.status_code}: {resp.text[:300]}")
    return False


def send_via_ghl(message: str) -> bool:
    api_key = os.environ.get("GHL_API_KEY", "").strip()
    location_id = os.environ.get("GHL_LOCATION_ID", "").strip()
    phone = os.environ.get("ALERT_PHONE", "").strip()

    if not (api_key and location_id and phone):
        print("(alerts) GHL env vars missing — skipping SMS path")
        return False

    try:
        contact_id = _ghl_find_contact_id(api_key, location_id, phone)
        if not contact_id:
            print("(alerts) contact not found — creating Site Monitor Alerts contact")
            contact_id = _ghl_create_contact(api_key, location_id, phone)
        if not contact_id:
            print("(alerts) could not get/create GHL contact — failing SMS path")
            return False
        ok = _ghl_send_sms(api_key, location_id, contact_id, message)
        if ok:
            print(f"(alerts) SMS sent via GHL to {phone}")
        return ok
    except requests.RequestException as exc:
        print(f"(alerts) GHL request error: {exc}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"(alerts) GHL unexpected error: {exc}")
        return False


# ---------------------------------------------------------------------------
# SMTP fallback
# ---------------------------------------------------------------------------

def send_via_email(message: str) -> bool:
    """
    Email fallback. Configure with:
      SMTP_HOST, SMTP_PORT (default 587), SMTP_USER, SMTP_PASS,
      SMTP_FROM, ALERT_EMAIL, optional SMTP_USE_SSL=1 for port-465 SSL.
    """
    host = os.environ.get("SMTP_HOST", "").strip()
    user = os.environ.get("SMTP_USER", "").strip()
    password = os.environ.get("SMTP_PASS", "").strip()
    sender = os.environ.get("SMTP_FROM", user).strip()
    recipient = os.environ.get("ALERT_EMAIL", "").strip()
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_ssl = os.environ.get("SMTP_USE_SSL", "0").strip() in ("1", "true", "True")

    if not (host and user and password and recipient):
        print("(alerts) SMTP env vars missing — skipping email path")
        return False

    msg = EmailMessage()
    msg["Subject"] = "fitaminos.com checkout monitor — ALERT"
    msg["From"] = sender or user
    msg["To"] = recipient
    msg.set_content(message)

    try:
        if use_ssl:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=HTTP_TIMEOUT) as s:
                s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=HTTP_TIMEOUT) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, password)
                s.send_message(msg)
        print(f"(alerts) email sent to {recipient}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"(alerts) SMTP error: {exc}")
        return False


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def send_alert(message: str) -> bool:
    """
    Try SMS via GHL first; if it fails or quiet hours, fall back to email.
    Returns True if at least one channel delivered.
    During quiet hours: skip SMS, send email only.
    """
    quiet_spec = os.environ.get("ALERT_QUIET_HOURS", "").strip()
    quiet = _parse_quiet_hours(quiet_spec) if quiet_spec else None
    in_quiet = bool(quiet and _in_quiet_hours(datetime.now(timezone.utc).astimezone(), *quiet))

    if in_quiet:
        print(f"(alerts) inside quiet hours {quiet_spec} — emailing instead of SMS")
        emailed = send_via_email(message)
        return emailed

    sms_ok = send_via_ghl(message)
    if sms_ok:
        return True

    print("(alerts) SMS failed — attempting email fallback")
    return send_via_email(message)


# ---------------------------------------------------------------------------
# CLI for quick manual testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    text = " ".join(sys.argv[1:]) or "fitaminos monitor — manual test alert"
    ok = send_alert(text)
    print("delivered" if ok else "ALL CHANNELS FAILED")
    sys.exit(0 if ok else 1)
