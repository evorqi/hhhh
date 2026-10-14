$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path .venv\Scripts\python.exe)) {
  py -3 -m venv .venv
  .\.venv\Scripts\python -m pip install -r requirements.txt
}
$env:PYTHONPATH = "$PSScriptRoot\src"
.\.venv\Scripts\python -m cleaning_workspace
