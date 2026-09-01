$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

frontline run
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$today = Get-Date -Format "yyyy-MM-dd"
$edition = "editions/$today.html"

if (Test-Path $edition) {
    Copy-Item $edition "editions/index.html" -Force
    git add editions/
    git commit -m "edition $today"
    git push personal main
} else {
    Write-Host "No new edition generated."
}
