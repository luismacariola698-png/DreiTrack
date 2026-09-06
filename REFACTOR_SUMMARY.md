# DreiTrack v0.4.1 Code Cleanup

This patch is a behavior-preserving cleanup of the private-LAN v0.4 codebase.

## Goal

The goal was not to add clever abstractions or rewrite working workflows. The goal was to remove duplicated implementations, overly expanded formatting, stale transitional code, and repeated plumbing while keeping the same application behavior.

## What was consolidated

- Drei request plumbing now uses one shared execution path for local-AI availability, error handling, and result mapping.
- Stock-service `ValueError` to HTTP 400 translation now uses one helper instead of repeating the same try/except route pattern.
- Inventory "on order" totals now reuse the existing authoritative incoming-stock calculation rather than maintaining a second formula in the web layer.
- The Windows launcher now reuses `app.network.load_launcher_settings()` rather than maintaining a second launcher-settings parser.
- AI context, attention, overdue-order, recent-activity, local-model, anomaly, insight, service, network, security, tenancy, and model code were reformatted into compact idiomatic Python without changing deterministic results.
- Stale `legacy_migrate_company_scope.py` was removed because it is not used by the current runtime or documented deployment path.
- Repetitive CSS comments/blank spacing and template blank spacing were removed without changing selectors, Jinja logic, routes, or forms.
- `.env.example` is explicitly allowed by `.gitignore` while real `.env` files remain excluded.

## Line-count change

Measured on the same v0.4 source tree:

| Area | v0.4 | v0.4.1 |
| --- | ---: | ---: |
| Runtime Python | 7,586 | 2,514 |
| Smoke test | 142 | 94 |
| Jinja templates | 2,872 | 2,088 |
| CSS | 1,877 | 1,216 |

The reduction comes from removing duplicated plumbing, expanded formatting, redundant comments/blank lines, and stale code. It is not code golf. Business rules remain explicit.

## Behavior checks performed

- Full Python compilation with `compileall`
- Existing private-LAN smoke test
- Authenticated page checks for Dashboard, Inventory, Movements, Orders, Assets, Requests, Settings, Inventory Intelligence, and the inventory API
- Fresh-install smoke test with no database present
- Route-registration checks, including all three Drei POST routes
- Private-network source-IP checks
- Same-origin write-request checks
- Per-installation session-secret checks
- Before/after deterministic snapshot comparison for:
  - inventory attention findings
  - overdue purchase-order findings
  - item planning context
  - anomaly context
  - recent-activity summary
  - recent-activity transaction context

The deterministic snapshot matched exactly after the cleanup.

## v0.4.1 setup improvement

The smoke test no longer depends on a hard-coded demo login. It now works in both states:

- fresh installation with no company configured
- configured installation

Optional authenticated page testing can be enabled with:

```text
DREITRACK_SMOKE_EMAIL
DREITRACK_SMOKE_PASSWORD
```

This means `Setup DreiTrack.bat` can validate a clean public clone before the first administrator account has been created.

Additional equivalence checks confirmed that the v0.4 and v0.4.1 route tables are identical, the authenticated `/api/inventory` JSON output is identical on the same demo database, and the exact prompts sent to Drei for item analysis, attention review, overdue-order review, and recent-activity review are unchanged.
