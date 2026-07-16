[CmdletBinding()]
param(
    [string]$OutputDirectory,
    [switch]$SkipDatabase
)

$ErrorActionPreference = 'Stop'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $root 'dist-vps'
}

New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
$bundlePath = Join-Path $OutputDirectory 'probora-vps.tar.gz'
$dumpPath = Join-Path $OutputDirectory 'probora.dump'

Push-Location $root
try {
    if (-not $SkipDatabase) {
        $postgresContainer = docker compose ps -q postgres
        if ([string]::IsNullOrWhiteSpace($postgresContainer)) {
            throw 'Local Probora PostgreSQL container is not running.'
        }

        docker compose exec -T postgres pg_dump -U probora -d probora -Fc -f /tmp/probora.dump
        if ($LASTEXITCODE -ne 0) {
            throw 'pg_dump failed.'
        }
        docker cp "${postgresContainer}:/tmp/probora.dump" $dumpPath
        if ($LASTEXITCODE -ne 0) {
            throw 'Could not copy probora.dump from the PostgreSQL container.'
        }
    }

    $excludes = @(
        '--exclude=src/**/bin',
        '--exclude=src/**/obj',
        '--exclude=web/probora-web/node_modules',
        '--exclude=web/probora-web/dist',
        '--exclude=infra/volumes'
    )
    $inputs = @(
        'docker-compose.vps.yml',
        '.env.vps.example',
        'Directory.Build.props',
        'Directory.Packages.props',
        'global.json',
        'src',
        'web',
        'infra',
        'artifacts/models'
    )
    & tar -czf $bundlePath @excludes @inputs
    if ($LASTEXITCODE -ne 0) {
        throw 'VPS bundle creation failed.'
    }
}
finally {
    Pop-Location
}

Write-Host "Bundle: $bundlePath"
if (-not $SkipDatabase) {
    Write-Host "Database: $dumpPath"
}
