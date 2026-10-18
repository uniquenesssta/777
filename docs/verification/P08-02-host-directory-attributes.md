# Deployment directory attributes

After HTTPS readiness succeeds, setup marks only the configured package, service root and hidden-backup directories Hidden + System. Directory is already inherent. Ordinary backup and child files remain unchanged. Primary upgrade and replica join both finish through the same setup path. A missing hidden-backup directory is created at the configured location; data is never reinitialized.

The package identity reader now explicitly accepts hidden roots. Existing pinned readers are upgraded only after their original owner/resource hashes are validated, with the deployment identity hash updated before hiding. Existing runner and native resources are retained.

The Windows PowerShell regression exercises all three attribute bits, unchanged ordinary backup, repeated application and reading through the actual copied identity reader after hiding. Local discovery: 14 tests, 6 passed, 8 Windows-only skipped. Windows runtime confirmation remains with CI; installer preparation is excluded.

Site follow-up (15:58): startup rejected `HOST_PACKAGE_FILE_SET_INVALID` before menu/business operations. The new visibility module was packaged but missing from the independent runtime allowlist; both lists now agree. Added real Windows PowerShell consumption of an assembled package, including rejection of extra/missing entries and a changed visibility module. No integrity checks are bypassed. Local discovery now totals 15 tests (6 passed, 9 Windows-only skipped).
