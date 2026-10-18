# Deployment directory attributes

After HTTPS readiness succeeds, setup marks the package directory, service root, and configured local fixed-disk backup directories named Quote777Hidden as Hidden + System. Backup roles do not control this decision: Quote777Hidden may be the ordinary backup. UNC shares, mapped network backup drives and differently named backup directories are excluded. Directory is already inherent and child files remain unchanged. Primary upgrade and replica join finish through the same setup path. Only a selected local Quote777Hidden directory may be created; no unconfigured sibling directory is invented and business data is never reinitialized.

The package identity reader now explicitly accepts hidden roots. Existing pinned readers are upgraded only after their original owner/resource hashes are validated, with the deployment identity hash updated before hiding. Existing runner and native resources are retained.

The Windows PowerShell regression exercises all three attribute bits, unchanged ordinary backup, repeated application and reading through the actual copied identity reader after hiding. Local discovery: 14 tests, 6 passed, 8 Windows-only skipped. Windows runtime confirmation remains with CI; installer preparation is excluded.

Site follow-up (15:58): startup rejected `HOST_PACKAGE_FILE_SET_INVALID` before menu/business operations. The new visibility module was packaged but missing from the independent runtime allowlist; both lists now agree. Added real Windows PowerShell consumption of an assembled package, including rejection of extra/missing entries and a changed visibility module. No integrity checks are bypassed. Local discovery now totals 15 tests (6 passed, 9 Windows-only skipped).

2026-10-18 16:22 site decision: .23 is running as primary and is left unchanged. Its ordinary backup is D:\Quote777Hidden and hidden backup is the .23 shared backup path, intentionally. The corrected package is for continuing the .38 replica deployment. Regression now covers reversed roles, an unchanged other backup directory, and exclusion of an unreachable UNC path even when its basename is Quote777Hidden.
