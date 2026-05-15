# Test Coverage Analysis

## Executive Summary

**Current State:** No tests exist. The project consists of two main modules (`monitor.py` and `alerts.py`) with zero test coverage.

**Risk:** Critical workflows (e.g., checkout monitoring and alert delivery) lack automated validation. Changes risk silent regressions that won't be caught until production runs fail.

**Recommendation:** Implement unit tests progressively, focusing first on high-risk logic in the alerts module and core monitor helpers, then integration tests for the full checkout flow (with mocked Playwright).

---

## Test Gap Analysis by Module

### `monitor.py` (19.2 KB, ~500 lines)

This module orchestrates a Playwright-driven synthetic checkout flow with five sequential steps and failure handling. Key risks and gaps:

#### **High-Priority Test Areas**

##### 1. **Data Model Validation** (Low Complexity)
- `StepResult` and `RunReport` dataclasses
- **What to test:**
  - Successful step tracking and result recording
  - Step failure detection and storage
  - `RunReport.ok` property reflects pass/fail correctly
  - Report timestamps and duration calculations
- **Why:** Ensures data integrity for failure reports and logging
- **Estimated effort:** 1–2 test cases

##### 2. **Helper Functions** (Low–Medium Complexity)
- `now_iso()` — ISO 8601 timestamp generation
- `_assert()` — custom assertion mechanism
- `dismiss_age_gate()` — age gate modal dismissal
- **What to test:**
  - `now_iso()` returns valid ISO 8601 UTC timestamps
  - `_assert()` raises `AssertionError` with the provided message on failure
  - `dismiss_age_gate()` correctly handles:
    - Modal present and visible → clicks and waits for dismissal
    - Modal not in DOM → no-op (idempotent)
    - Modal in DOM but hidden → no-op
    - Missing confirm button → logs warning but doesn't crash
    - Playwright timeout on visibility check → graceful fallback
- **Why:** These are utility functions used throughout the monitor; bugs here break all downstream steps
- **Estimated effort:** 3–5 test cases (with mocked Playwright)

##### 3. **Step Execution Pipeline** (Medium Complexity)
- `_run_step()` — orchestrates step execution, exception handling, and result tracking
- **What to test:**
  - Successful step: logs "PASS", appends result, returns True
  - Failed step: logs "FAIL", sets `report.failed_step`, appends result, returns False
  - Duration calculation is reasonable (within 10-50ms tolerance)
  - Exception message and type are captured in `StepResult.detail`
  - URL extraction from exceptions works or falls back safely
- **Why:** This function is the backbone of the monitoring loop; failure here loses context
- **Estimated effort:** 4–6 test cases

##### 4. **Individual Step Functions** (Medium–High Complexity)
Each step (`step_homepage`, `step_shop`, `step_add_to_cart`, `step_cart_renders`, `step_checkout_renders`) combines Playwright selectors with assertions. Testing requires mocking Page/Browser objects.

###### **`step_homepage(page)`**
- **What to test:**
  - Valid response (200–399) with brand marker → passes
  - Bad HTTP status (4xx, 5xx) → raises with status code
  - Missing "Fitaminos" text AND no brand image → raises
  - Brand image alt-text fallback works
  - Age gate is dismissed post-navigation
- **Why:** Homepage is the entry point; if this fails, the entire run aborts
- **Estimated effort:** 3–4 test cases

###### **`step_shop(page)`**
- **What to test:**
  - Valid response with products (fallback selector matching) → passes with correct count
  - No products found (all selectors return 0) → raises
  - Bad HTTP status → raises
  - Handles multiple WooCommerce selector variants
  - Age gate dismissed
- **Why:** Shop page loads must be reliable; test selector fallback logic
- **Estimated effort:** 3–4 test cases

###### **`step_add_to_cart(page)` — HIGHEST COMPLEXITY**
- **What to test:**
  - **Path A: PRODUCT_URL points to /shop/** → navigate /shop/, pick first product link, navigate to product, click add button, wait for confirmation
  - **Path B: PRODUCT_URL is a direct product URL** → navigate directly, click add button, wait for confirmation
  - **Path C: Add button click succeeds but no confirmation notice** → fallback to /cart/ and check cart form exists
  - Button selector fallback (4 variants) finds a visible, clickable button
  - Floating add-to-cart button is excluded (display:none edge case)
  - Missing add button → raises
  - Playwright timeout on button visibility → raises with detail
  - Page navigation settled state is detected
  - Age gate dismissed
- **Why:** Add-to-cart is the most complex step with conditional logic; regressions here break the entire checkout flow
- **Estimated effort:** 6–8 test cases

###### **`step_cart_renders(page)` & `step_checkout_renders(page)`**
- **What to test:**
  - Valid response with required DOM elements (cart items, totals, checkout button) → passes
  - Missing any required element → raises
  - Button click navigates to checkout page
  - Checkout URL verification and billing/payment fields exist
  - Fallback navigation when button missing
  - Age gate dismissed
- **Why:** Validate that downstream pages render correctly
- **Estimated effort:** 4–5 test cases per step

##### 5. **Integration Test: `run_checks()`** (High Complexity, High Value)
- **What to test:**
  - Full flow: all 5 steps succeed → report.ok = True, no failed_step
  - First failure aborts remaining steps → correct failed_step set, screenshot/DOM captured
  - Browser/context cleanup on success and on failure
  - Cookie pre-seeding for age gate
  - Screenshot saving on failure
  - DOM excerpt captured (first 4000 chars)
  - Handles browser startup failure gracefully
- **Why:** End-to-end validation ensures the entire checkout flow works
- **Estimated effort:** 3–4 test cases (with mocked Playwright context)

##### 6. **Report Generation** (Low Complexity)
- `write_failure_report()` — Markdown report generation
- `write_run_summary()` — JSON summary generation
- **What to test:**
  - Report contains all expected sections (header, step table, DOM excerpt)
  - JSON is valid and includes all fields
  - Handles missing screenshot path and DOM excerpt gracefully
  - Reports written to correct `ARTIFACT_DIR`
- **Why:** Operators rely on these reports to diagnose failures
- **Estimated effort:** 2–3 test cases

##### 7. **Main Entry Point & Error Handling** (Medium Complexity)
- `main()` function
- **What to test:**
  - All checks pass → returns 0, no alert sent
  - First step fails → returns 1, alert sent with step name and URL
  - Catastrophic startup failure (Playwright can't start) → returns 2, crash alert sent
  - Alert failure doesn't crash the monitor (logged but continues)
  - Reports written before alert attempt
- **Why:** Exit codes and alert delivery are critical for CI integration
- **Estimated effort:** 3–4 test cases

#### **Recommended Test Strategy for `monitor.py`**
1. **Mock Playwright.** Use `unittest.mock.MagicMock` to simulate Page, Response, and Locator objects.
2. **Parameterized tests.** Test each step with 3–4 scenarios (success, missing element, timeout, bad status).
3. **Fixtures.** Create reusable mock page, browser, and context fixtures.
4. **Integration test.** Mock the full flow once unit tests pass.
5. **No live site.** All tests must be hermetic; never call fitaminos.com.

---

### `alerts.py` (10.5 KB, ~304 lines)

This module handles alert delivery via GoHighLevel SMS (primary) and SMTP email (fallback). Logic bugs here can cause missed alerts—critical for a monitoring tool.

#### **High-Priority Test Areas**

##### 1. **Quiet Hours Parsing** (Low Complexity)
- `_parse_quiet_hours(spec: str)`
- **What to test:**
  - Valid format `"22:00-06:00"` → returns (time(22, 0), time(6, 0))
  - Valid format with spaces `"22:00 - 06:00"` → parses correctly
  - Invalid formats (missing colon, non-numeric, bad separator) → returns None, logs warning
  - Empty string → returns None
  - 24h format boundary cases (e.g., `"00:00-23:59"`)
- **Why:** Malformed quiet hours silently disable SMS suppression, causing alerts during sleep
- **Estimated effort:** 4–5 test cases

##### 2. **Quiet Hours Logic** (Low Complexity)
- `_in_quiet_hours(now: datetime, start: time, end: time)`
- **What to test:**
  - Simple range (08:00–17:00):
    - 08:00 (start boundary) → True
    - 16:59 (inside) → True
    - 17:00 (end boundary, exclusive) → False
    - 07:59 (before) → False
  - Midnight-wrapping range (22:00–06:00):
    - 22:00 (start) → True
    - 23:30 (after start) → True
    - 05:59 (before end) → True
    - 06:00 (end boundary) → False
    - 12:00 (outside) → False
  - Edge cases: 00:00, 23:59, matching start/end times
- **Why:** Quiet hours that don't respect midnight wraparound cause alerts during intended quiet periods
- **Estimated effort:** 6–8 test cases

##### 3. **GoHighLevel API Functions** (Medium Complexity)
- `_ghl_find_contact_id(api_key, location_id, phone)`
- `_ghl_create_contact(api_key, location_id, phone)`
- `_ghl_send_sms(api_key, location_id, contact_id, message)`

**These require mocking `requests`:**
- **`_ghl_find_contact_id`** — What to test:
  - Contact found → returns ID
  - Contact not found → returns None
  - Phone matching handles spaces (E.164 normalization)
  - HTTP 200 with empty contacts list → returns None
  - HTTP 401/403 (auth failure) → returns None, logs error
  - Timeout/connection error → returns None, logs error
- **Why:** Contact lookup failure silently prevents SMS delivery
- **`_ghl_create_contact`** — What to test:
  - Valid creation (HTTP 200/201) → returns ID
  - Duplicate error (HTTP 400) → falls back to find, returns ID if found
  - Other 4xx/5xx errors → returns None, logs error
  - Network error → returns None
  - Payload includes correct tags and source
- **Why:** Contact creation is retry logic; gaps here cause missed SMS on first run
- **`_ghl_send_sms`** — What to test:
  - HTTP 200/201/202 success codes → returns True
  - HTTP 4xx/5xx → returns False
  - Network timeout → returns False
  - Payload structure correct (type=SMS, contactId, message, locationId)
  - Headers include Authorization and Version
- **Why:** SMS delivery success must be reliable
- **Estimated effort:** 6–8 test cases total for all 3 GHL functions

##### 4. **Email Sending** (Medium Complexity)
- `send_via_email(message, sms_failed=False)`
- **What to test:**
  - With valid creds (SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL) → sends, returns True
  - Missing any required env var → logs warning, returns False
  - SMTP timeout → returns False, logs error
  - SSL variant (SMTP_USE_SSL=1, port 465) uses `SMTP_SSL` context
  - TLS variant (SMTP_USE_SSL=0, port 587) uses `SMTP` with `starttls()`
  - Message subject differs when `sms_failed=True`
  - From field defaults to SMTP_USER if SMTP_FROM not set
  - Message body includes "[SMS DELIVERY FAILED]" prefix when `sms_failed=True`
- **Why:** Email is the fallback; if email also fails silently, alerts don't reach operator
- **Estimated effort:** 5–6 test cases

##### 5. **SMS-First, Email-Fallback Logic** (High Complexity, High Value)
- `send_alert(message)`
- **What to test:**
  - **Normal hours, SMS succeeds:**
    - SMS called and returns True → email NOT called, returns True
    - Logs indicate SMS sent, email skipped
  - **Normal hours, SMS fails:**
    - SMS called and returns False → email called with sms_failed=True, returns True/False
    - Logs indicate SMS failed, email fallback attempted
  - **Quiet hours, SMS/email creds both set:**
    - SMS NOT called, email called directly, returns True/False
    - Logs indicate inside quiet hours
  - **Quiet hours, missing email creds:**
    - SMS skipped but no alert delivered, returns False
  - **No quiet hours env var set:**
    - Behaves as normal hours
  - **Malformed quiet hours:**
    - Treated as no quiet hours, proceeds normally
  - **Both SMS and email fail:**
    - Returns False, logs final "BOTH CHANNELS FAILED"
  - **Unhandled exception in SMS path:**
    - Caught, email fallback triggered, returns email result
- **Why:** This is the critical decision logic; regressions cause missed alerts or double-sends
- **Estimated effort:** 8–10 test cases

##### 6. **Environment Variable Handling** (Medium Complexity)
- **What to test across all functions:**
  - `.strip()` is applied to all env var reads (no leading/trailing whitespace issues)
  - Unset env vars default to "" (not None)
  - Empty string is treated as "not set" (falsy check works)
  - Numeric env vars are cast correctly (SMTP_PORT as int)
  - Boolean env vars (SMTP_USE_SSL) parse "1", "true", "True" correctly
- **Why:** Silent env var misreadings cause failures in CI/CD
- **Estimated effort:** 3–4 test cases

##### 7. **CLI Interface** (Low Complexity)
- `if __name__ == "__main__"` block
- **What to test:**
  - With args: `python alerts.py "test message"` → calls `send_alert("test message")`
  - Without args: defaults to generic test message
  - Exit code 0 on success, 1 on failure
- **Why:** Manual testing via CLI is documented in README; it must work
- **Estimated effort:** 2–3 test cases

#### **Recommended Test Strategy for `alerts.py`**
1. **Mock `requests` library.** Use `unittest.mock.patch` to mock HTTP calls.
2. **Mock `smtplib`.** Mock SMTP and SMTP_SSL context managers.
3. **Use timezone-aware datetime fixtures.** Test quiet hours with fixed `now` values.
4. **Parameterized tests.** Test each API variant (GHL contact find/create/send, email SSL/TLS) with success/failure/timeout scenarios.
5. **No live API calls.** All tests must be hermetic.

---

## Cross-Module & Integration Considerations

### **Test Isolation**
- `monitor.py` should **not** import `alerts.py` for testing; mock the `send_alert()` import.
- `alerts.py` tests should **not** call `monitor.py`.
- No test should read real env vars from the host machine (use `unittest.mock.patch.dict(os.environ, {...})` to mock env).

### **CI/CD Integration**
- Add `pytest` and `pytest-cov` to `requirements-dev.txt`.
- Configure pytest with `pytest.ini` or `pyproject.toml` to:
  - Discover tests in `tests/` directory
  - Generate coverage reports (target: 80%+ initially)
  - Set warnings as errors (to catch deprecations early)
- GitHub Actions workflow: add a test step before deploying the monitor.

### **Regression Risk by Area**

| Area | Risk Level | Impact | Suggested Priority |
|------|-----------|--------|-------------------|
| Quiet hours logic | **High** | Silent SMS suppression misfire | **1st** |
| SMS/email fallback decision | **High** | Missed alerts or double-sends | **1st** |
| Add-to-cart selector fallback | **High** | Monitor fails on theme changes | **2nd** |
| Error handling in main() | **Medium** | Crashed monitor doesn't alert | **2nd** |
| GHL API contact lookup | **Medium** | SMS fails if contact doesn't exist | **3rd** |
| Step execution pipeline | **Medium** | Context lost on failure | **3rd** |
| Report generation | **Low** | Diagnostics incomplete | **4th** |

---

## Proposed Testing Roadmap

### **Phase 1: Foundation (Week 1)**
- Set up test infrastructure: `requirements-dev.txt`, `pytest.ini`, basic fixtures
- Write tests for `alerts.py`:
  - Quiet hours parsing and logic (10–12 test cases)
  - SMS/email fallback decision tree (10–12 test cases)
  - Environment variable handling (3–4 test cases)
- **Target:** 60+ test cases, 90%+ coverage of `alerts.py`

### **Phase 2: Monitor Unit Tests (Week 2)**
- Write tests for `monitor.py` helpers:
  - Data models, `now_iso()`, `_assert()`, `dismiss_age_gate()` (5–10 test cases)
  - `_run_step()` orchestration (4–6 test cases)
- **Target:** 40+ test cases, 70%+ coverage of `monitor.py` helpers

### **Phase 3: Step Functions (Week 3)**
- Write tests for each individual step function:
  - Homepage, shop, add-to-cart, cart, checkout (15–20 test cases)
- Use mocked Playwright Page objects with realistic selector/response scenarios
- **Target:** 40+ test cases, 80%+ coverage of step functions

### **Phase 4: Integration & CLI (Week 4)**
- Write integration test for `run_checks()` full flow
- Write CLI test for `alerts.py` command-line interface
- Add coverage reporting and CI integration
- **Target:** 20+ test cases, 85%+ overall coverage

---

## Summary: Proposed Areas for Improvement

### **alerts.py** (Highest ROI)
1. ✅ Test quiet hours parsing and time-range logic (midnight wraparound edge cases)
2. ✅ Test SMS-first, email-fallback decision tree in `send_alert()`
3. ✅ Mock GHL API: contact lookup, creation, SMS send
4. ✅ Mock SMTP email: success and failure scenarios
5. ✅ Environment variable handling and defaults

### **monitor.py** (Medium-High Priority)
1. ✅ Data model validation (StepResult, RunReport)
2. ✅ Helper functions (now_iso, _assert, dismiss_age_gate)
3. ✅ Step execution pipeline (_run_step) with exception handling
4. ✅ Individual step functions with selector fallback testing
5. ✅ Add-to-cart step (highest complexity, most failure modes)
6. ✅ Full integration test (run_checks with mocked Playwright)
7. ✅ Report generation (Markdown and JSON)
8. ✅ Main entry point and error handling

### **Infrastructure**
1. ✅ Add `requirements-dev.txt` with pytest, pytest-cov, pytest-mock
2. ✅ Create `tests/` directory with structured layout
3. ✅ Add `pytest.ini` or `pyproject.toml` with coverage config
4. ✅ Add GitHub Actions step to run tests before deployment
5. ✅ Reach 85%+ code coverage

---

## Estimated Effort

- **Unit tests (alerts.py):** 40–50 lines per test × 15–20 tests = 600–1000 LOC
- **Unit tests (monitor.py):** 40–60 lines per test × 25–30 tests = 1000–1800 LOC
- **Fixtures and utilities:** 200–300 LOC
- **CI/CD config:** 50–100 LOC
- **Total:** ~2500–3500 lines of test code for ~800 lines of production code
- **Time estimate:** 3–4 weeks for one developer, or 1–2 weeks with two developers focused on one module at a time
