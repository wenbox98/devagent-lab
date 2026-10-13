# Non-destructive preflight. No installation, privilege changes or network calls.
$ErrorActionPreference = 'Stop'
$taskRoot = (Resolve-Path (Join-Path $PSScriptRoot '../..')).Path
$taskPreviousLocation = Get-Location
try {
    Set-Location -LiteralPath $taskRoot
    Write-Host 'L08: verify Windows Job controls; repository execution stays blocked.'
    Write-Host 'No filesystem/network sandbox backend is implemented. A separately approved'
    Write-Host 'sandbox setup and adapter with boundary tests is required before repository execution.'
    & python -m devagent.runtime.environment
    $taskExitCode = $LASTEXITCODE
} finally {
    Set-Location -LiteralPath $taskPreviousLocation.Path
}
exit $taskExitCode
