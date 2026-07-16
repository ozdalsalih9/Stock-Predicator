param(
    [Parameter(Mandatory = $true)]
    [string]$BackupFile
)

$ErrorActionPreference = "Stop"
$resolved = Resolve-Path -LiteralPath $BackupFile
Get-Content -Raw -LiteralPath $resolved | docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U probora -d probora
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL restore verification failed." }
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U probora -d probora -c "SELECT count(*) FROM probora.assets;"
