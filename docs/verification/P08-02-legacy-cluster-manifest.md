# Legacy standalone manifest upgrade

The 2026-10-18 site log confirms that elevation, authenticated resource selection, primary enrollment and generation 1 snapshot publication succeeded. Failure followed the final inspect/status calls, before task restart. The original standalone manifest has no `deployment_mode`; assigning a missing PSCustomObject property under PowerShell strict mode fails.

Cluster completion now adds or replaces only the two cluster metadata properties after the existing ownership, resource, ledger and certificate checks. Retrying menu 8 retains the same ledger, certificate and existing cluster. No reinitialization or directory deletion is required.

The Windows upgrade regression fixture now starts with the legacy missing field and checks that interrupted upgrade retry retains identity and writes cluster mode. Console failure logs include exception type and script basename/line, without exception messages or credential contents.

Local checks: 14 deployment tests discovered, 6 passed and 8 Windows-only tests skipped; diff whitespace check passed. Actual PowerShell 5.1 execution must be confirmed by Windows CI. Mother/sales installer preparation is not requested.
