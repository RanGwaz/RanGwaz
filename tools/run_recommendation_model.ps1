$ErrorActionPreference = "Stop"

if (-not $env:PYTHONIOENCODING) {
  $env:PYTHONIOENCODING = "utf-8"
}

Write-Host "Recommendation model service: http://127.0.0.1:8092"
python "$PSScriptRoot\recommendation_model_service.py"
