# Run stl2gif in a virtual environment (creates .venv if missing)
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$Activate = Join-Path $VenvPath "Scripts\Activate.ps1"

if (-not (Test-Path $VenvPath)) {
    Write-Host "Creating virtual environment at $VenvPath ..."
    python -m venv $VenvPath
}
& $Activate
pip install -q -r (Join-Path $ProjectRoot "requirements.txt")
python (Join-Path $ProjectRoot "stl2gif.py") @args
