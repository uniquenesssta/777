# Deployment directory attributes

After HTTPS readiness succeeds, setup marks only the configured package, service root and hidden-backup directories Hidden + System. Directory is already inherent. Ordinary backup and child files remain unchanged. Primary upgrade and replica join both finish through the same setup path. A missing hidden-backup directory is created at the configured location; data is never reinitialized.

The package identity reader now explicitly accepts hidden roots. Existing pinned readers are upgraded only after their original owner/resource hashes are validated, with the deployment identity hash updated before hiding. Existing runner and native resources are retained.

The Windows PowerShell regression exercises all three attribute bits, unchanged ordinary backup, repeated application and reading through the actual copied identity reader after hiding. Local discovery: 14 tests, 6 passed, 8 Windows-only skipped. Windows runtime confirmation remains with CI; installer preparation is excluded.
