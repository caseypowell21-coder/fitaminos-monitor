"""
monitor.py v1.0.0
Synthetic checkout monitor for fitaminos.com.

Runs a sequenced set of checks against the live site simulating a real
customer's path from homepage -> shop -> product -> cart -> checkout.
Each check is pass/fail. On the first failure we capture a screenshot,
URL, and DOM excerpt, fire an SMS alert via GoHighLevel, write a
failure report, and exit non-zero so GitHub Actions marks the run red.

Designed for Python 3.11+ with Playwright (sync API).
"""

from __future__ import annotations

import os
import sys
import json
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from playwright.sync_api import (
    sync_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
)

from alerts import send_alert

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

VERSION = "1.0.0"
BASE_URL = "https://fitaminos.com"

# A known, stable product URL. If/when this product is retired, swap it
# for a more stable one (or read from env var PRODUCT_URL).
# NOTE: use `or` rather than the default arg of os.environ.get(): GitHub
# Actions expands an unset `vars.PRODUCT_URL` to the empty string, not
# "unset", so `.get(key, default)` would return "" and break page.goto().
PRODUCT_URL = os.environ.get("PRODUCT_URL") or f"{BASE_URL}/shop/"

DEFAULT_TIMEOUT_MS = 20_000  # 20s per page action
NAV_TIMEOUT_MS = 25_000

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 FitaminosMonitor/" + VERSION
)

ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", "."))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Result tracking
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    url: str = ""
    duration_ms: int = 0


@dataclass
class RunReport:
    started_at: str
    finished_at: str = ""
    steps: list[StepResult] = field(default_factory=list)
    failed_step: StepResult | None = None
    screenshot_path: str = ""
    dom_excerpt: str = ""

    @property
    def ok(self) -> bool:
        return self.failed_step is None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# Step helpers
# ---------------------------------------------------------------------------

def _run_step(
    report: RunReport,
    name: str,
    fn: Callable[[], tuple[str, str]],
) -> bool:
    """Run a single step. fn returns (detail, current_url). Raises on failure."""
    started = datetime.now(timezone.utc)
    try:
        detail, url = fn()
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        result = StepResult(name=name, ok=True, detail=detail, url=url, duration_ms=elapsed_ms)
        report.steps.append(result)
        print(f"PASS  {name}  ({elapsed_ms}ms)  {url}")
        return True
    except Exception as exc:  # noqa: BLE001 — we want any failure
        elapsed_ms = int((datetime.now(timezone.utc) - started).total_seconds() * 1000)
        detail = f"{type(exc).__name__}: {exc}"
        url = ""
        try:
            url = exc.args[1] if len(exc.args) > 1 else ""
        except Exception:
            pass
        result = StepResult(name=name, ok=False, detail=detail, url=url, duration_ms=elapsed_ms)
        report.steps.append(result)
        report.failed_step = result
        print(f"FAIL  {name}  ({elapsed_ms}ms)  {detail}")
        return False


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def step_homepage(page: Page) -> tuple[str, str]:
    response = page.goto(BASE_URL, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    _assert(response is not None, "no response object")
    status = response.status if response else 0
    _assert(200 <= status < 400, f"unexpected HTTP status {status}")
    body = page.content().lower()
    has_brand = ("fitaminos" in body) or page.locator("img[alt*='Fitaminos' i]").count() > 0
    _assert(has_brand, "homepage missing 'Fitaminos' brand marker")
    return f"status={status}, brand marker found", page.url


def step_shop(page: Page) -> tuple[str, str]:
    response = page.goto(f"{BASE_URL}/shop/", timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    _assert(response is not None, "no response object")
    status = response.status if response else 0
    _assert(200 <= status < 400, f"unexpected HTTP status {status}")
    # WooCommerce default product list selectors
    product_selectors = [
        "ul.products li.product",
        ".woocommerce ul.products",
        ".products .product",
        ".wc-block-grid__products .wc-block-grid__product",
    ]
    found = 0
    for sel in product_selectors:
        try:
            count = page.locator(sel).count()
            if count > 0:
                found = count
                break
        except Exception:
            continue
    _assert(found > 0, "no product elements on /shop/ — selectors all empty")
    return f"status={status}, products visible={found}", page.url


def step_add_to_cart(page: Page) -> tuple[str, str]:
    """
    Visit a product page, click Add to cart, look for a confirmation cue.
    If PRODUCT_URL points at /shop/ we pick the first product link.
    """
    if PRODUCT_URL.rstrip("/").endswith("/shop"):
        # Already on shop or going to it. Pick the first product and
        # navigate directly to its href rather than .click()ing the
        # wrapping <a> — in the Fitaminos theme (and several other WC
        # themes) the LoopProduct-link is a zero-area wrapper around an
        # absolutely-positioned image, so Playwright's "visible, enabled
        # and stable" check loops forever. goto() bypasses that and is
        # equivalent from the customer's perspective.
        page.goto(f"{BASE_URL}/shop/", timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        first_link = page.locator("ul.products li.product a.woocommerce-LoopProduct-link, "
                                  ".products .product a.woocommerce-LoopProduct-link, "
                                  ".products .product a[href*='/product/']").first
        _assert(first_link.count() > 0, "no product link found on /shop/")
        href = first_link.get_attribute("href", timeout=DEFAULT_TIMEOUT_MS)
        _assert(bool(href) and "/product/" in href,
                f"first product link missing /product/ href: {href!r}")
        page.goto(href, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    else:
        response = page.goto(PRODUCT_URL, timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        _assert(response is not None and 200 <= response.status < 400,
                f"product page status {response.status if response else 'none'}")

    # Exclude the Fitaminos theme's `floating_add_to_cart_button` — that
    # variant lives in the DOM ahead of the in-product button but is
    # display:none until the page scrolls past the price block, so .first
    # picks an invisible element and Playwright's click loops on the
    # visibility check.
    add_btn = page.locator(
        "button.single_add_to_cart_button:not(.floating_add_to_cart_button), "
        "form.cart button[type=submit]:not(.floating_add_to_cart_button), "
        "button[name='add-to-cart']:not(.floating_add_to_cart_button), "
        "a.add_to_cart_button:not(.floating_add_to_cart_button)"
    ).first
    _assert(add_btn.count() > 0, "Add to cart button not found on product page")
    add_btn.click(timeout=DEFAULT_TIMEOUT_MS)

    # Wait for any of: WC notice, mini-cart update, or page navigation settled.
    try:
        page.wait_for_selector(
            ".woocommerce-message, .woocommerce-notices-wrapper .wc-block-components-notice-banner, "
            ".cart-contents-count, .added_to_cart",
            timeout=DEFAULT_TIMEOUT_MS,
        )
    except PlaywrightTimeoutError:
        # Fall back: re-check cart contents directly
        page.goto(f"{BASE_URL}/cart/", timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
        _assert(page.locator(".woocommerce-cart-form, .wc-block-cart").count() > 0,
                "cart confirmation never appeared and /cart/ has no cart form")

    return "add-to-cart click registered", page.url


def step_cart_renders(page: Page) -> tuple[str, str]:
    response = page.goto(f"{BASE_URL}/cart/", timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")
    _assert(response is not None and 200 <= response.status < 400,
            f"/cart/ status {response.status if response else 'none'}")

    # An item line should be visible
    has_item = page.locator(
        ".woocommerce-cart-form .cart_item, "
        ".wc-block-cart-items__row, "
        ".cart_item"
    ).count() > 0
    _assert(has_item, "cart appears empty — no cart_item rows")

    # Total visible
    has_total = page.locator(
        ".cart-subtotal, .order-total, .wc-block-components-totals-item, .cart_totals"
    ).count() > 0
    _assert(has_total, "cart totals block not found")

    # Proceed to Checkout button visible
    checkout_btn = page.locator(
        "a.checkout-button, .wc-proceed-to-checkout a, a[href*='/checkout']"
    ).first
    _assert(checkout_btn.count() > 0, "Proceed to Checkout button not found")

    return "cart populated, totals + checkout button visible", page.url


def step_checkout_renders(page: Page) -> tuple[str, str]:
    checkout_btn = page.locator(
        "a.checkout-button, .wc-proceed-to-checkout a, a[href*='/checkout']"
    ).first
    if checkout_btn.count() > 0:
        with page.expect_navigation(timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded"):
            checkout_btn.click(timeout=DEFAULT_TIMEOUT_MS)
    else:
        # Fallback: navigate directly
        page.goto(f"{BASE_URL}/checkout/", timeout=NAV_TIMEOUT_MS, wait_until="domcontentloaded")

    _assert("/checkout" in page.url, f"did not land on /checkout/ — at {page.url}")

    # Billing fields present (classic checkout) OR block checkout container
    has_billing = (
        page.locator("#billing_first_name, #billing_email").count() > 0
        or page.locator(".wc-block-checkout, .wp-block-woocommerce-checkout").count() > 0
    )
    _assert(has_billing, "no billing form fields or block-checkout container found")

    # Payment options visible
    has_payment = (
        page.locator("#payment, .wc-block-checkout__payment-method, .payment_methods").count() > 0
    )
    _assert(has_payment, "no payment methods block visible on /checkout/")

    return "checkout page billing + payment blocks visible (no submit)", page.url


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_checks() -> RunReport:
    report = RunReport(started_at=now_iso())

    with sync_playwright() as p:
        browser: Browser = p.chromium.launch(headless=True)
        context: BrowserContext = browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        context.set_default_timeout(DEFAULT_TIMEOUT_MS)
        context.set_default_navigation_timeout(NAV_TIMEOUT_MS)
        page = context.new_page()

        steps: list[tuple[str, Callable[[], tuple[str, str]]]] = [
            ("homepage_loads", lambda: step_homepage(page)),
            ("shop_page_loads", lambda: step_shop(page)),
            ("add_to_cart", lambda: step_add_to_cart(page)),
            ("cart_page_renders", lambda: step_cart_renders(page)),
            ("checkout_page_renders", lambda: step_checkout_renders(page)),
        ]

        for name, fn in steps:
            ok = _run_step(report, name, fn)
            if not ok:
                # Capture artifacts on first failure
                screenshot = ARTIFACT_DIR / f"failure-{name}.png"
                try:
                    page.screenshot(path=str(screenshot), full_page=True)
                    report.screenshot_path = str(screenshot)
                except Exception as exc:
                    print(f"(could not save screenshot: {exc})")
                try:
                    html = page.content()
                    report.dom_excerpt = html[:4000]
                    report.failed_step.url = page.url  # type: ignore[union-attr]
                except Exception:
                    pass
                break

        try:
            browser.close()
        except Exception:
            pass

    report.finished_at = now_iso()
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def write_failure_report(report: RunReport) -> Path:
    path = ARTIFACT_DIR / "failure-report.md"
    failed = report.failed_step
    lines = [
        "# fitaminos.com checkout monitor — FAILURE",
        "",
        f"- Monitor version: `{VERSION}`",
        f"- Started:  `{report.started_at}`",
        f"- Finished: `{report.finished_at}`",
        f"- Failed step: **{failed.name if failed else 'unknown'}**",
        f"- URL at failure: `{failed.url if failed else ''}`",
        f"- Screenshot: `{report.screenshot_path or 'n/a'}`",
        "",
        "## Step results",
        "",
        "| step | result | duration_ms | detail |",
        "| --- | --- | --- | --- |",
    ]
    for s in report.steps:
        status = "✅ pass" if s.ok else "❌ FAIL"
        lines.append(f"| {s.name} | {status} | {s.duration_ms} | {s.detail} |")

    if report.dom_excerpt:
        lines += [
            "",
            "## DOM excerpt (first 4000 chars)",
            "",
            "```html",
            report.dom_excerpt,
            "```",
        ]

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def write_run_summary(report: RunReport) -> None:
    path = ARTIFACT_DIR / "run-summary.json"
    payload = {
        "version": VERSION,
        "started_at": report.started_at,
        "finished_at": report.finished_at,
        "ok": report.ok,
        "steps": [s.__dict__ for s in report.steps],
        "failed_step": report.failed_step.__dict__ if report.failed_step else None,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"fitaminos checkout monitor v{VERSION} — starting at {now_iso()}")
    try:
        report = run_checks()
    except Exception as exc:  # catastrophic: Playwright failed to start
        print(f"FATAL — monitor itself crashed: {exc}")
        traceback.print_exc()
        try:
            send_alert(
                f"fitaminos.com monitor CRASHED at startup — {type(exc).__name__}: {exc}"
            )
        except Exception as alert_exc:
            print(f"(alert also failed: {alert_exc})")
        return 2

    write_run_summary(report)

    if report.ok:
        print(f"ALL CHECKS PASSED — finished {report.finished_at}")
        return 0

    # Failure path
    failed = report.failed_step
    report_path = write_failure_report(report)
    print(f"Wrote failure report: {report_path}")

    msg = (
        f"fitaminos.com checkout monitor FAIL at step "
        f"[{failed.name}] — {failed.url or 'unknown URL'} at {report.finished_at}"
    )
    try:
        send_alert(msg)
    except Exception as alert_exc:
        print(f"(SMS+email alert both failed: {alert_exc})")

    return 1


if __name__ == "__main__":
    sys.exit(main())
