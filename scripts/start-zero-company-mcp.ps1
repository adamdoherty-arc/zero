param(
    [ValidateSet("stdio", "sse", "streamable-http")]
    [string]$Transport = "streamable-http",
    [string]$HostName = "127.0.0.1",
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"

$repo = "C:\code\zero"
$server = Join-Path $repo "mcp_servers\zero_company_mcp.py"

if (-not (Test-Path $server)) {
    throw "Zero Company MCP server not found: $server"
}

$env:ZERO_COMPANY_MCP_TRANSPORT = $Transport
$env:ZERO_COMPANY_MCP_HOST = $HostName
$env:ZERO_COMPANY_MCP_PORT = "$Port"

Set-Location $repo
python $server --transport $Transport
