<#
  Demo 3 (live) - drive the OPEN Workflow.aprx end to end, on camera.

  Pairs with region_workflow.py: run that first to build demos\_sample\Workflow.aprx,
  open it in ArcGIS Pro (Map view active, add-in installed / bridge on :5005), then
  run this. Each command acts on the live project so you can record the map react:
  zoom -> query -> buffer appears -> dissolve -> zoom -> export the finished layout.

  powershell -ExecutionPolicy Bypass -File demos\demo_live_workflow.ps1
#>

$ErrorActionPreference = "Stop"
$here = $PSScriptRoot
$Bridge = "http://127.0.0.1:5005/"
$gdb = Join-Path $here "_sample\workflow.gdb"
$cities = "$gdb\cities"
$buf100 = "$gdb\cities_100km"
$cov100 = "$gdb\coverage_100km"
$pdf = Join-Path $here "_sample\Nepal_live_export.pdf"

function Send {
  param([string]$desc, [hashtable]$cmd, [int]$pause = 3)
  Write-Host ""
  Write-Host "  >>> $desc" -ForegroundColor Cyan
  $body = $cmd | ConvertTo-Json -Compress -Depth 6
  Write-Host "  POST $body" -ForegroundColor DarkGray
  Start-Sleep -Milliseconds 800
  $r = Invoke-RestMethod -Uri $Bridge -Method Post -Body $body -ContentType "application/json"
  Write-Host ($r | ConvertTo-Json -Depth 6)
  Start-Sleep -Seconds $pause
}

if (-not (Test-NetConnection 127.0.0.1 -Port 5005 -WarningAction SilentlyContinue).TcpTestSucceeded) {
  Write-Host "Bridge not reachable. Open Workflow.aprx in ArcGIS Pro with the add-in installed." -ForegroundColor Red
  exit 1
}

Clear-Host
Write-Host "=== Live workflow on the OPEN ArcGIS Pro project - watch the map ===" -ForegroundColor Green

Send "1) What project is open?" @{ command = "ping" }
Send "2) Zoom to the cities" @{ command = "zoom_to"; layer = "Cities" }
Send "3) Biggest cities (population > 200k)" @{ command = "query"; layer = "Cities"; where = "POP_MAX > 200000"; limit = 10 }
Send "4) What if 100 km service areas? Run a buffer - watch it appear" @{ command = "run_gp"; tool = "analysis.Buffer"; params = @($cities, $buf100, "100 Kilometers") } 4
Send "5) Dissolve the 100 km buffers into one coverage area" @{ command = "run_gp"; tool = "analysis.PairwiseDissolve"; params = @($buf100, $cov100) } 4
Send "6) Zoom to the expanded coverage" @{ command = "zoom_to"; layer = "coverage_100km" }
Send "7) Export the finished cartographic layout to PDF" @{ command = "export_layout"; layout = "Nepal Service Areas"; out = $pdf; dpi = 200 }

Write-Host ""
Write-Host "=== Done. Analysis to finished map, driven live by an agent. ===" -ForegroundColor Green
if (Test-Path $pdf) { Start-Process $pdf }  # pop the exported map as the finale
