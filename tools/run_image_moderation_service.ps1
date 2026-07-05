$ErrorActionPreference = "Stop"

$ToolsDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPython = Join-Path $ToolsDir ".venv\Scripts\python.exe"
$Python = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

if (-not $env:VIBELO_IMAGE_MODERATION_MODE) {
  $env:VIBELO_IMAGE_MODERATION_MODE = "heuristic"
}
if (-not $env:VIBELO_IMAGE_MODERATION_PORT) {
  $env:VIBELO_IMAGE_MODERATION_PORT = "8093"
}

Write-Host "Image moderation service: http://127.0.0.1:$env:VIBELO_IMAGE_MODERATION_PORT"
Write-Host "Mode: $env:VIBELO_IMAGE_MODERATION_MODE"
& $Python (Join-Path $ToolsDir "image_moderation_service.py")
