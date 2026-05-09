# Ecosystem audit run - 2026-05-02 - company folder migration

## Scope

Moved the operating center of gravity from `C:\code\ArchitectureMaster` to
`C:\code\zero`.

## Implemented

- Created the company folder structure:
  - `docs\00-company`
  - `docs\10-constitution`
  - `docs\20-products`
  - `docs\30-strategy`
  - `docs\40-operations`
  - `plans\active`
  - `plans\archive\claude-import-2026-05-02`
  - `.agents\skills\ecosystem-audit`
  - `scripts`
- Migrated the canonical ArchitectureMaster docs into company-native locations.
- Imported the active plan to `plans\active\review-the-two-lively-cascade.md`.
- Imported 239 historical Claude plan files into the company plan archive.
- Added company operating docs:
  - `README.md`
  - `docs\README.md`
  - `docs\00-company\COMPANY_OPERATING_MODEL.md`
  - `docs\20-products\PRODUCT_PORTFOLIO.md`
  - `plans\README.md`
- Updated Zero, Legion, and Ada mandates to reference `C:\code\zero`.
- Updated the ecosystem-audit skill text to treat company docs as canonical.
- Converted ArchitectureMaster docs and validator into compatibility pointers.

## Verification

Command:

```powershell
powershell -ExecutionPolicy Bypass -File C:\code\zero\scripts\validate-company.ps1
```

Result:

- Passed.
- Warning remains: `ada-mcp` references `C:\code\ADA\mcp_servers\ada_mcp.py`,
  which is still missing and queued as Q11.

## Open drift carried forward

1. Add `c:\code\zero` to Legion's managed-project registry (Q16).
2. Decide git/repository strategy for the company folder (Q17).
3. Implement Ada MCP compatibility server (Q11).
4. Align Ada `.mcp.json` after the server exists (Q12).
5. Implement Legion `company.*` audit/drift/queue interfaces (Q14).

<!-- agent-run-id: 67b5b32a-89e4-4aee-a58e-0381c0d8e8c0 source: ecosystem-audit at: 2026-05-02T-run-2 -->

