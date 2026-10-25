# Offline installer routing check. PlanOnly returns before filesystem/OS changes.
$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'Install-SelectQueue.ps1'
$root = Join-Path $env:TEMP ('zink-plan-' + [guid]::NewGuid())
$argsCommon = @{ NativeDirectory='unused'; Wheel='unused'; Python='unused'; Root=$root; PlanOnly=$true }
$fill = & $installer @argsCommon -Mode Live | ConvertFrom-Json
$preserve = & $installer @argsCommon -Mode Live -PreparationMode PreserveEdges | ConvertFrom-Json
$capture = & $installer @argsCommon -PreparationMode PreserveEdges | ConvertFrom-Json
if ($fill.queue -ne 'HP Sprocket Select' -or $fill.port -ne 8631 -or $fill.preparation_mode -ne 'fill') { throw 'Borderless queue defaults changed.' }
if ($preserve.queue -ne 'HP Sprocket Select (Preserve edges)' -or $preserve.port -ne 8632 -or $preserve.preparation_mode -ne 'preserve-edges') { throw 'Wrong Preserve edges layout.' }
if ($fill.root -eq $preserve.root -or $fill.task -eq $preserve.task -or $fill.data -eq $preserve.data) { throw 'Queue profiles must have separate runtime, task and data.' }
if (!$preserve.requires_existing_borderless_live) { throw 'The second live queue requires the existing shared journal.' }
if ($capture.queue -ne 'HP Sprocket Select (Preserve edges) (capture)' -or $capture.requires_existing_borderless_live) { throw 'Wrong capture layout.' }
if (Test-Path $root) { throw 'Offline planning unexpectedly created files.' }
Write-Output 'Offline installer layout checks passed; no queues, services, files or Bluetooth changed.'
