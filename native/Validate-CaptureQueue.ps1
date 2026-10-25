# Sends synthetic pages through the Windows spooler ONLY to the capture queue.
# The explicit config/process guards must pass before PrintDocument.Print().
[CmdletBinding()]
param(
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'ZinkProbe'),
    [ValidateSet('Fill','PreserveEdges')][string]$PreparationMode = 'Fill'
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
if ($PreparationMode -eq 'PreserveEdges') { $Root = Join-Path $Root 'preserve-edges' }
$data = Join-Path $Root 'capture'
$configPath = Join-Path $data 'config.json'
$config = Get-Content $configPath -Raw | ConvertFrom-Json
if ($config.mode -ne 'capture' -or $config.address -or $config.device_id) { throw 'This check requires a capture-only configuration without printer credentials.' }
$processes = @(Get-CimInstance Win32_Process -Filter "Name = 'zink-ipp.exe'" | Where-Object { $_.CommandLine.Contains('"' + $configPath + '"') })
if ($processes.Count -ne 1 -or !$processes[0].CommandLine.Contains($configPath)) { throw 'The running bridge must be the capture instance.' }
$queueName = if ($PreparationMode -eq 'PreserveEdges') { 'HP Sprocket Select (Preserve edges) (capture)' } else { 'HP Sprocket Select (capture)' }
$queue = Get-Printer -Name $queueName
if ($queue.DriverName -ne 'Microsoft IPP Class Driver') { throw 'Expected Windows native IPP Class Driver.' }
Add-Type -AssemblyName System.Drawing
function Send-CapturePage([bool]$landscape, [int]$pages) {
    $doc = New-Object System.Drawing.Printing.PrintDocument
    try {
        $doc.PrinterSettings.PrinterName = $queueName
        $doc.PrintController = New-Object System.Drawing.Printing.StandardPrintController
        $doc.DocumentName = "Zink capture validation landscape=$landscape pages=$pages"
        $doc.PrinterSettings.Copies = 1
        $paper = @($doc.PrinterSettings.PaperSizes | Where-Object { $_.Width -ge 227 -and $_.Width -le 230 -and $_.Height -ge 341 -and $_.Height -le 344 })
        if ($paper.Count -ne 1) { throw 'Windows did not expose the expected 58 x 87 mm paper.' }
        $doc.DefaultPageSettings.PaperSize = $paper[0]
        $doc.DefaultPageSettings.Landscape = $landscape
        $doc.DefaultPageSettings.Color = $true
        $doc.DefaultPageSettings.Margins = New-Object System.Drawing.Printing.Margins(0,0,0,0)
        $script:pageNumber = 0
        $doc.add_PrintPage({
            param($sender,$e)
            $e.Graphics.Clear([Drawing.Color]::White)
            $font = New-Object Drawing.Font('Arial',12)
            try {
                $e.Graphics.DrawString('CAPTURE ONLY', $font, [Drawing.Brushes]::Black, 10, 12)
                $e.Graphics.FillRectangle([Drawing.Brushes]::Red,10,50,40,60)
                $e.Graphics.FillRectangle([Drawing.Brushes]::Lime,55,50,40,60)
                $e.Graphics.FillRectangle([Drawing.Brushes]::Blue,100,50,40,60)
                $e.Graphics.DrawRectangle([Drawing.Pens]::Black,5,5,($e.PageBounds.Width-10),($e.PageBounds.Height-10))
                $e.Graphics.DrawString("$($e.PageBounds.Width) x $($e.PageBounds.Height)", $font, [Drawing.Brushes]::Black,10,120)
            } finally { $font.Dispose() }
            $script:pageNumber++
            $e.HasMorePages = $script:pageNumber -lt $pages
        }.GetNewClosure())
        $doc.Print()
    } finally { $doc.Dispose() }
}
Send-CapturePage $false 1
Start-Sleep -Seconds 4
Send-CapturePage $true 1
Start-Sleep -Seconds 4
# Deliberately unsupported two-page document: native callback must reject the
# complete job with no worker invocation (no partially dispatched first page).
Send-CapturePage $false 2
Start-Sleep -Seconds 4
Get-ChildItem "$data/jobs/*/result.json" | ForEach-Object { Get-Content $_ -Raw | ConvertFrom-Json } | Select-Object local_id,state,mode,source_size,jpeg_bytes,bluetooth_opened | ConvertTo-Json
Get-PrintJob -PrinterName $queueName | Select-Object ID,DocumentName,JobStatus
