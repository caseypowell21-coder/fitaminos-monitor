# Test Coverage Analysis - fitaminos-monitor

## Executive Summary

**Current State**: ❌ **ZERO** unit test coverage (0%)

The codebase has no test suite, test framework, or automated testing infrastructure. While the project includes automated synthetic monitoring (which is valuable), there is no unit or integration testing for the core business logic in `alerts.py` and `monitor.py`.

**Risk Level**: 🔴 **HIGH**

- Silent failures in alerting logic could prevent operators from knowing about site outages
- Refactoring is risky without test coverage
- Edge cases in time parsing and API interactions are untested
- Regression detection relies solely on manual execution

---

## Coverage Analysis by Module

### 1. `alerts.py` - Alerting Module (CRITICAL COVERAGE NEEDED)

**Lines of Code**: ~304 lines | **Test Coverage**: 0%

#### Functions with zero test coverage:

| Function | Complexity | Risk | Why Test? |
|----------|-----------|------|-----------|
| `_parse_quiet_hours()` | Low | HIGH | Parses time ranges; failures silently disable alert suppression |
| `_in_quiet_hours()` | Low | HIGH | Quiet hours logic bug means alerts fire at wrong times |
| `_ghl_find_contact_id()` | Medium | HIGH | API integration; no test for contact lookup failure modes |
| `_ghl_create_contact()` | Medium | HIGH | Handles both new creation and duplicate detection; untested edge cases |
| `_ghl_send_sms()` | Medium | HIGH | Primary alerting path; no test for HTTP status codes, timeouts, malformed responses |
| `send_via_ghl()` | Medium | HIGH | Orchestrates contact lookup/creation and SMS; error handling paths untested |
| `send_via_email()` | Medium | HIGH | SMTP fallback; no test for connection failures, auth errors, timeout behavior |
| `send_alert()` | High | CRITICAL | Main entry point; quiet hours + SMS-first logic untested; no test for dual-channel fallback |

#### Critical untested scenarios in `alerts.py`:

1. **Quiet Hours Edge Cases**
   - Time parsing with invalid formats (e.g., "25:00", "23:60", "22:00-06:00" vs wrapping midnight)
   - Boundary conditions (exactly at start/end time)
   - UTC vs local timezone handling
   - Missing or empty `ALERT_QUIET_HOURS` env var

2. **GHL API Integration**
   - Contact lookup returns empty list
   - Contact creation returns 400 "duplicate" error (should retry lookup)
   - HTTP 429 (rate limit) or 503 (service unavailable)
   - Malformed JSON response
   - Missing required fields in response (e.g., `contact.id`)
   - Different success status codes (200 vs 201 vs 202)

3. **SMS-First, Email-Fallback Logic** (v1.1.0 fix)
   - SMS succeeds → email must NOT fire
   - SMS fails (4xx/5xx) → email should fire
   - Quiet hours active → email fires, SMS is suppressed
   - Both SMS and email fail → correct error message

4. **SMTP Email Fallback**
   - Missing credentials don't crash the process
   - Connection timeout behavior
   - Authentication failures
   - TLS/SSL mode selection (`SMTP_USE_SSL`)
   - Port handling (default 587, override for 465)
   - `[SMS DELIVERY FAILED]` subject/body prefix applied correctly when sms_failed=True

5. **Environment Variables**
   - Missing/empty GHL_API_KEY, GHL_LOCATION_ID, ALERT_PHONE
   - Missing/empty SMTP credentials
   - Malformed ALERT_QUIET_HOURS values (should be logged, not crash)

---

### 2. `monitor.py` - Synthetic Monitor Module (MEDIUM COVERAGE NEEDED)

**Lines of Code**: ~507 lines | **Test Coverage**: 0%

#### Functions with zero test coverage:

| Function | Complexity | Risk | Why Test? |
|----------|-----------|------|-----------|
| `_run_step()` | Medium | MEDIUM | Wraps step execution and error handling; timing calculation untested |
| `_assert()` | Low | LOW | Simple assertion helper; could use a test for clarity |
| `dismiss_age_gate()` | Medium | MEDIUM | EMAV overlay dismissal; idempotent but complex locator logic |
| `step_homepage()` | Medium | MEDIUM | First check; HTTP status validation, brand marker detection untested |
| `step_shop()` | Medium | MEDIUM | Product selector fallback logic (4 selectors); unclear which path taken |
| `step_add_to_cart()` | High | HIGH | Most complex step; conditional product lookup + floating button exclusion + notification wait |
| `step_cart_renders()` | Medium | MEDIUM | Multiple product selector variants; cart total detection untested |
| `step_checkout_renders()` | Medium | MEDIUM | Navigation logic (button click vs direct goto); billing form detection untested |
| `run_checks()` | High | MEDIUM | Orchestration; browser setup, artifact capture, step sequencing untested without live site |
| `write_failure_report()` | Low | LOW | Report formatting; mostly I/O, but output format could regress |
| `write_run_summary()` | Low | LOW | JSON serialization; minimal logic but data integrity worth testing |
| `main()` | High | MEDIUM | Entry point; error handling paths, exit codes, alert firing untested |

#### Critical untested scenarios in `monitor.py`:

1. **Step Execution & Error Handling**
   - Exception caught in `_run_step()` → correct detail/URL extraction
   - Timing calculation (elapsed_ms) accuracy
   - First failure stops further steps (no continuing after failure)
   - Failed step stored correctly in report

2. **Age Gate Dismissal (EMAV)**
   - Overlay visible → dismissed correctly
   - Overlay not in DOM → idempotent (no error)
   - Overlay visible but confirm button missing → logged, not fatal
   - Confirm button click fails with timeout → logged, doesn't break flow
   - Overlay still visible 5s after click → logged warning

3. **Homepage Check**
   - HTTP 2xx status → pass
   - HTTP 3xx redirect → pass
   - HTTP 4xx/5xx → fail with correct detail
   - No response object → fail with "no response object"
   - Brand marker detection: "Fitaminos" in body text OR image alt attribute

4. **Shop Page Check**
   - Tries all 4 product selectors in order
   - Returns count from first selector that finds products
   - All selectors empty → fails
   - HTTP non-2xx status → fails

5. **Add to Cart Complex Flow**
   - PRODUCT_URL ends with "/shop" → finds first product link, extracts href, navigates
   - PRODUCT_URL is specific product → navigates directly
   - Finds correct "Add to cart" button (excludes floating variant)
   - Waits for notification/mini-cart update (has fallback to direct /cart/ nav)
   - Handles cases where notification never appears

6. **Cart Page Check**
   - Multiple cart form selector variants
   - Total detection from 4 different selectors
   - Checkout button locator

7. **Checkout Page Check**
   - Button click triggers navigation
   - Fallback: direct navigation if no button found
   - Lands on /checkout (URL validation)
   - Billing form detection (classic vs block checkout)
   - Payment methods block detection

8. **Report Generation**
   - Failed step data included correctly
   - Screenshot path set
   - DOM excerpt truncated to 4000 chars
   - Markdown formatting correct
   - JSON serialization of StepResult objects (dataclass __dict__)

9. **Main Entry Point**
   - Success path: exit code 0
   - Failure path: exit code 1
   - Crash path: exit code 2, alert sent
   - Failure report written
   - Run summary written
   - Alert sent on failure

---

## Recommended Test Strategy

### Phase 1: Unit Tests (HIGHEST PRIORITY)

**Focus**: `alerts.py` core logic - testable without external APIs

**Scope**:
- Quiet hours parsing and time checking (`_parse_quiet_hours`, `_in_quiet_hours`)
- Report generation (`write_failure_report`, `write_run_summary`)
- Time/timestamp utilities (`now_iso`)

**Tools**:
- `pytest` - test framework
- `pytest-mock` or `unittest.mock` - mock HTTP requests
- `freezegun` - time mocking

**Example test scenarios**:
```python
def test_parse_quiet_hours_valid():
    assert _parse_quiet_hours("22:00-06:00") == (time(22, 0), time(6, 0))

def test_in_quiet_hours_wrapping_midnight():
    # 23:00 with quiet hours 22:00-06:00 should return True
    
def test_send_alert_sms_succeeds_suppresses_email():
    # Mock GHL API to return 200, verify email NOT sent
    
def test_send_alert_sms_fails_fires_email():
    # Mock GHL API to return 500, verify email IS sent
```

**Estimated effort**: 8-12 hours
**Coverage target**: 80%+ of `alerts.py`

---

### Phase 2: Integration Tests (MEDIUM PRIORITY)

**Focus**: Alert delivery paths without mocking entire HTTP layer

**Scope**:
- Mock GHL and SMTP APIs, test alert logic end-to-end
- Test quiet hours integration with alert dispatch
- Test email-as-fallback triggering

**Tools**:
- `responses` library for mocking requests
- `pytest-asyncio` if we add async later
- `smtp4dev` or similar for SMTP testing (optional)

**Example scenarios**:
```python
@responses.activate
def test_ghl_send_sms_with_retry_on_duplicate():
    # Mock first create attempt returns 400 "duplicate"
    # Verify retry logic calls lookup
    
@responses.activate
def test_quiet_hours_blocks_sms_sends_email():
    # Set ALERT_QUIET_HOURS to current time
    # Mock both APIs, verify SMS endpoint not called
```

**Estimated effort**: 6-10 hours
**Coverage target**: Alert dispatch logic

---

### Phase 3: Monitor.py Unit Tests (MEDIUM PRIORITY)

**Focus**: Testable helpers without browser automation

**Scope**:
- `_run_step` wrapper timing and error handling
- `_assert` helper
- Report generation functions
- Time/UUID generation

**Tools**:
- Same pytest + mock setup
- `unittest.mock` for Playwright Page objects

**Example scenarios**:
```python
def test_run_step_success_timing():
    # Mock successful step, verify elapsed_ms calculated
    
def test_run_step_failure_extracts_detail_and_url():
    # Mock exception, verify detail and URL captured correctly
    
def test_write_failure_report_markdown_format():
    # Create report, verify markdown valid
```

**Estimated effort**: 6-8 hours
**Coverage target**: 60%+ of `monitor.py` (excluding Playwright-dependent code)

---

### Phase 4: Playwright-Based Integration Tests (LOWEST PRIORITY)

**Focus**: Synthetic checks against a test site or mock

**Scope**:
- Full step execution (homepage, shop, cart, checkout)
- Age gate dismissal
- Error capture (screenshot, DOM)

**Tools**:
- `pytest-playwright` for test fixtures
- Mock WooCommerce site or use staging environment

**Challenge**: Requires either a staging environment or a full mock e-commerce site. Lower ROI since the live monitor already does integration testing.

**Estimated effort**: 12-16 hours
**Coverage target**: End-to-end flows

---

## Implementation Roadmap

### Step 1: Set up test infrastructure (2 hours)
```bash
# Add to requirements-dev.txt
pytest==7.x
pytest-mock==3.x
freezegun==1.x
responses==0.x

# Add to pyproject.toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-v --tb=short"

# Create tests/ directory structure
tests/
├── __init__.py
├── conftest.py
├── test_alerts.py
├── test_monitor.py
└── fixtures/
    └── sample_responses.py
```

### Step 2: Write alerts.py tests (8-10 hours)
- Start with quiet hours logic (simple, high impact)
- Mock GHL and SMTP APIs
- Test SMS-first, email-fallback logic
- Test edge cases and env var handling

### Step 3: Write monitor.py tests (6-8 hours)
- Test report generation
- Test step wrapper timing
- Mock Playwright Page objects for simple checks
- Test error detail extraction

### Step 4: Add CI/CD test step (1 hour)
```yaml
- name: Run tests
  run: pytest tests/ -v --cov=alerts --cov=monitor --cov-report=term-missing
```

### Step 5: Improve coverage over time
- Refactor for testability (e.g., extract API calls to separate functions)
- Add Playwright integration tests against staging

---

## Key Risks of Current State

1. **Silent Alerting Failures**: Bug in `send_alert()` could prevent critical alerts
2. **Quiet Hours Logic Bug**: Could suppress alerts during business hours or send during off-hours
3. **API Integration Issues**: GHL or SMTP changes could break without detection
4. **Refactoring Risk**: Hard to safely improve code without tests
5. **Regression Detection**: Only caught by manual testing or live site failures

---

## Quick Wins (Low Effort, High Impact)

1. **Test quiet hours parsing** (1-2 hours)
   - ~50 lines of test code
   - Catches parsing bugs immediately
   - No mocking needed

2. **Test alert delivery decision logic** (2-3 hours)
   - Mock requests library
   - Verify SMS-first, email-fallback behavior
   - ~200 lines of test code

3. **Test report generation** (1-2 hours)
   - No mocking needed
   - Verify markdown format
   - Catch data loss bugs

---

## Recommended Next Steps

1. **Immediate** (this sprint):
   - Add `pytest` to requirements-dev.txt
   - Create `tests/` directory
   - Write tests for quiet hours logic (`_parse_quiet_hours`, `_in_quiet_hours`)
   - Write tests for report generation

2. **Short-term** (next 1-2 sprints):
   - Mock requests and test all alert paths
   - Test main entry point and error handling
   - Get to 60%+ coverage for `alerts.py`

3. **Medium-term** (next month):
   - Full `alerts.py` coverage (80%+)
   - `monitor.py` helper function coverage
   - CI/CD integration

4. **Long-term**:
   - Playwright integration tests against staging
   - Full end-to-end test scenarios

---

## Dependencies & Tools

**Testing Framework**:
- `pytest==7.4+` - test runner
- `pytest-mock==3.11+` - mocking support
- `freezegun==1.2+` - time mocking
- `responses==0.23+` - HTTP request mocking
- `pytest-cov==4.1+` - coverage reporting

**Development Dependencies**:
- Keep in `requirements-dev.txt` (not `requirements.txt`)
- Don't add to production dependencies

**CI/CD**:
- Add pytest step to `.github/workflows/monitor.yml` BEFORE the monitor step
- Fail build if tests fail

---

## Success Metrics

✅ All unit tests written and passing
✅ Coverage >= 60% overall, >= 80% for `alerts.py`
✅ CI/CD runs tests on every PR
✅ No "untested edge case" bugs in production
✅ Safe refactoring with regression detection
