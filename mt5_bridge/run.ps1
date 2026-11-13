$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv")) { py -m venv .venv }
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m mt5_bridge.app
