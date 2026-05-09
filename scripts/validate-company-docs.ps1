param(
    [string]$Root = "C:\code\zero"
)

$ErrorActionPreference = "Stop"

$docsRoot = Join-Path $Root "docs\company"
$failures = New-Object System.Collections.Generic.List[string]

function Add-Failure([string]$Message) { $script:failures.Add($Message) | Out-Null }

if (-not (Test-Path $docsRoot)) {
    Add-Failure "Missing company docs root: $docsRoot"
} else {
    $required = @(
        "INDEX.md",
        "company-operating-model.md",
        "llc-compliance.md",
        "agent-company-structure.md",
        "task-management-system.md",
        "finance-procurement-system.md",
        "dashboard-spec.md",
        "consulting-playbook.md",
        "product-robotics-roadmap.md",
        "second-brain-sync.md",
        "sources.md",
        "architecture.md",
        "mandate.md",
        "master-plan.md",
        "living-state.md",
        "project-structure.md",
        "merged-plan-index.md",
        "product-portfolio.md",
        "agentic-os.md",
        "second-brain.md"
    )

    foreach ($file in $required) {
        $path = Join-Path $docsRoot $file
        if (-not (Test-Path $path)) {
            Add-Failure "Missing company doc: $path"
            continue
        }
        $content = Get-Content -Raw -LiteralPath $path
        if ($file -ne "INDEX.md" -and $content -notmatch "Active Zero context") {
            Add-Failure "Missing migration context banner: $path"
        }
    }

    $index = Join-Path $docsRoot "INDEX.md"
    if (Test-Path $index) {
        $indexContent = Get-Content -Raw -LiteralPath $index
        foreach ($needle in @("Zero is the active software home", "Notion is deferred", "approval records")) {
            if ($indexContent -notmatch [regex]::Escape($needle)) {
                Add-Failure "INDEX.md missing expected phrase: $needle"
            }
        }
    }
}

$frontendChecks = @(
    "frontend\src\pages\CompanyOsPage.tsx",
    "frontend\src\config\navigation.ts",
    "frontend\src\data\company-os.ts"
)

foreach ($file in $frontendChecks) {
    $path = Join-Path $Root $file
    if (-not (Test-Path $path)) {
        Add-Failure "Missing frontend company surface: $path"
    }
}

$backendChecks = @(
    "backend\app\services\company_context_service.py"
)

foreach ($file in $backendChecks) {
    $path = Join-Path $Root $file
    if (-not (Test-Path $path)) {
        Add-Failure "Missing backend company context file: $path"
    }
}

if ($failures.Count -gt 0) {
    Write-Host "Company docs validation failed:" -ForegroundColor Red
    $failures | ForEach-Object { Write-Host " - $_" -ForegroundColor Red }
    exit 1
}

Write-Host "Zero Company OS docs validation passed." -ForegroundColor Green
exit 0
