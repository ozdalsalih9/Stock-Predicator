param(
    [string]$OutputDirectory = "backups"
)

$ErrorActionPreference = "Stop"
$resolved = Join-Path (Get-Location) $OutputDirectory
New-Item -ItemType Directory -Force -Path $resolved | Out-Null
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$output = Join-Path $resolved "probora-$stamp.sql"
docker compose exec -T postgres pg_dump --clean --if-exists --no-owner -U probora -d probora | Set-Content -Encoding utf8 $output
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed." }
Write-Output $output
