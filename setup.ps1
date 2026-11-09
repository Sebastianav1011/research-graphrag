param(
    [string]$Python = '3.14.0',
    [string]$VenvPath = '.venv',
    [ValidateSet('cu128','cpu')][string]$TorchBackend = 'cu128',
    [switch]$Dev,
    [switch]$IncludePdf,
    [switch]$IncludeSensors
)
$ErrorActionPreference = 'Stop'
$repoRoot = $PSScriptRoot
function Invoke-UvChecked {
    param([string[]]$Arguments)
    & uv @Arguments
    if ($LASTEXITCODE -ne 0) { throw "uv termino con codigo $LASTEXITCODE" }
}
$previousEnvironment = $env:UV_PROJECT_ENVIRONMENT
Push-Location -LiteralPath $repoRoot
try {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'Instale uv (Astral) y reabra la terminal. Consulte README.md: Inicio rapido.'
    }
    if ($TorchBackend -ne 'cu128') {
        throw 'El lock vigente conserva CUDA 12.8. No se cambia torch a CPU por fuera de uv.lock; consulte docs/instalacion.md.'
    }
    $target = [IO.Path]::GetFullPath((Join-Path $repoRoot $VenvPath))
    if (-not $target.StartsWith($repoRoot.TrimEnd('\')+'\',[StringComparison]::OrdinalIgnoreCase)) {
        throw 'VenvPath debe estar dentro del repositorio.'
    }
    $env:UV_PROJECT_ENVIRONMENT = $target
    # Adopt the current environment without removing unrelated packages.
    # dev is a separate group included by default; -Dev remains compatible.
    $syncArguments = @('sync','--locked','--inexact','--python',$Python)
    if ($IncludePdf) { $syncArguments += @('--group','pdf') }
    if ($IncludeSensors) { $syncArguments += @('--group','performance') }
    Invoke-UvChecked $syncArguments
    Invoke-UvChecked @('run','--locked','python','scripts/check_environment.py','--skip-external')
    Write-Host 'Entorno preparado con uv. Iniciar desde la raiz: uv run python run.py'
    Write-Host 'Ollama solo se necesita para el proveedor local; pesos y fuentes autorizadas se preparan aparte.'
} finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousEnvironment
    Pop-Location
}
