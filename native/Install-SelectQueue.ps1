# Run in PowerShell as the Windows user who paired the printer (administrator).
# Capture is the safe default. Live mode makes a subsequent application Print
# action consume paper. Installation itself never submits a print job.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$NativeDirectory,
    [Parameter(Mandatory=$true)][string]$Wheel,
    [Parameter(Mandatory=$true)][string]$Python,
    [ValidateSet('Capture','Live')][string]$Mode = 'Capture',
    [ValidateSet('Fill','PreserveEdges')][string]$PreparationMode = 'Fill',
    [string]$DeviceConfig,
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'ZinkProbe'),
    [int]$Port = 0,
    [switch]$PlanOnly
)
$ErrorActionPreference = 'Stop'
$baseRoot = $Root
$preserve = $PreparationMode -eq 'PreserveEdges'
$layout = if ($preserve) { 'preserve-edges' } else { 'fill' }
$taskName = if ($preserve) { 'ZinkProbe-Select-PreserveEdges' } else { 'ZinkProbe-Select' }
$baseName = if ($preserve) { 'HP Sprocket Select (Preserve edges)' } else { 'HP Sprocket Select' }
$captureName = "$baseName (capture)"
$queueName = if ($Mode -eq 'Live') { $baseName } else { $captureName }
if ($preserve) { $Root = Join-Path $baseRoot 'preserve-edges' }
if ($Port -eq 0) { $Port = if ($preserve) { 8632 } else { 8631 } }
if ($Port -lt 1 -or $Port -gt 65535) { throw 'Port must be 1..65535.' }
$data = Join-Path $Root $Mode.ToLowerInvariant()
if ($PlanOnly) {
    # Pure offline layout inspection: no printer, task, files or permissions changed.
    @{ queue=$queueName; task=$taskName; root=$Root; data=$data; port=$Port; preparation_mode=$layout; requires_existing_borderless_live=($preserve -and $Mode -eq 'Live') } | ConvertTo-Json
    return
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this installation as administrator, using the account that paired the Select.' }
if ($Root.Contains('"') -or $Root -match '[^\x20-\x7E]') { throw 'This initial Windows package requires an ASCII installation path without quotes.' }
if (Test-Path $data) { throw "The $Mode data directory already exists. Preserve it; this installer does not overwrite jobs or repeat an activation." }
if (Get-Printer -Name $queueName -ErrorAction SilentlyContinue) { throw "Printer already exists: $queueName" }
if ($Mode -eq 'Live') {
    if (!$DeviceConfig) { throw 'Live mode requires a private device.json with paired address and device_id.' }
    $device = Get-Content $DeviceConfig -Raw | ConvertFrom-Json
    if ($device.address -notmatch '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$' -or $device.device_id -notmatch '^[0-9a-fA-F]{32}$') { throw 'Invalid private device identity.' }
    if ($preserve) {
        # Both queues must share the existing durable claim/uncertain-job journal.
        # Separate journals could allow a second queue to bypass the first lock.
        $borderlessConfig = Join-Path $baseRoot 'live/config.json'
        if (!(Test-Path $borderlessConfig)) { throw 'Install the borderless Live queue first so both layouts can share its job journal.' }
        $borderless = Get-Content $borderlessConfig -Raw | ConvertFrom-Json
        if ($borderless.schema -ne 1 -or $borderless.mode -ne 'live' -or $borderless.address -ne $device.address -or $borderless.device_id -ne $device.device_id) { throw 'Both queues must target the same validated printer identity.' }
        $sharedJournal = if ($borderless.journal_path) { $borderless.journal_path } else { Join-Path $borderless.data_dir 'jobs.sqlite' }
        if (![IO.Path]::IsPathRooted($sharedJournal)) { throw 'The borderless journal path must be absolute.' }
    }
    $old = Get-Printer -Name $captureName -ErrorAction SilentlyContinue
    if ($old -and @(Get-PrintJob -PrinterName $old.Name).Count) { throw 'Finish or cancel all capture queue jobs before activating.' }
    $capture = Join-Path $Root 'capture'
    if (@(Get-ChildItem "$capture/incoming/*.rgb" -ErrorAction SilentlyContinue).Count) { throw 'Unresolved capture rasters remain; inspect them before activation.' }
    foreach ($claim in Get-ChildItem "$capture/jobs/*/claim.json" -ErrorAction SilentlyContinue) {
        $resultPath = Join-Path $claim.DirectoryName 'result.json'
        if (!(Test-Path $resultPath) -or (Get-Content $resultPath -Raw | ConvertFrom-Json).state -ne 'captured') { throw 'An unresolved capture worker exists; inspect it before activation.' }
    }
}
foreach ($privateRoot in (@($baseRoot, $Root) | Select-Object -Unique)) {
    if (!(Test-Path $privateRoot)) {
        New-Item -ItemType Directory $privateRoot | Out-Null
        & icacls $privateRoot /inheritance:r /grant:r "*$($identity.User.Value):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
        if ($LASTEXITCODE) { throw 'Could not restrict the private installation directory.' }
    }
}
$venvPython = Join-Path $Root 'venv/Scripts/python.exe'
if (!(Test-Path $venvPython)) {
    & $Python -m venv (Join-Path $Root 'venv')
    if ($LASTEXITCODE) { throw 'Python environment creation failed.' }
}
& $venvPython -m pip install --upgrade --force-reinstall "$Wheel[images]"
if ($LASTEXITCODE) { throw 'Python package installation failed.' }
$existingTask = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existingTask) {
    if ($Mode -ne 'Live') { throw 'An existing bridge task must be inspected before replacement.' }
    Stop-ScheduledTask -TaskName $taskName
    Start-Sleep -Seconds 2
}
if (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) { throw 'The chosen local port is still in use.' }
$bin = Join-Path $Root 'bin'
New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item (Join-Path $NativeDirectory '*') $bin -Recurse -Force
foreach ($directory in @($data, "$data/incoming", "$data/jobs", "$data/spool")) { New-Item -ItemType Directory $directory | Out-Null }
$config = @{schema=1; mode=$Mode.ToLowerInvariant(); data_dir=$data; transport='auto'; preparation_mode=$layout}
if ($Mode -eq 'Live') {
    if ($preserve) { $config.journal_path = $sharedJournal }
    $config.address = $device.address
    $config.device_id = $device.device_id
    $epoch = [DateTime]::Parse('1970-01-01T00:00:00Z').ToUniversalTime()
    $config.live_after_ns = [long](([DateTime]::UtcNow.Ticks - $epoch.Ticks) * 100)
}
$configPath = Join-Path $data 'config.json'
$config | ConvertTo-Json | Set-Content -Encoding UTF8 $configPath
$exe = Join-Path $bin 'zink-ipp.exe'
$arguments = '"{0}" "{1}" "{2}" "{3}" "{4}" {5}' -f $venvPython,$configPath,"$data/incoming","$data/spool","$data/bridge.log",$Port
$action = New-ScheduledTaskAction -Execute $exe -Argument $arguments -WorkingDirectory $Root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$taskPrincipal = New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $taskPrincipal -Settings $settings -Description 'Local IPP to HP Sprocket Select Bluetooth bridge. One page and one copy per job.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
$ready = $false
for ($i=0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    if (Get-NetTCPConnection -State Listen -LocalAddress '127.0.0.1' -LocalPort $Port -ErrorAction SilentlyContinue) { $ready=$true; break }
}
if (!$ready) { throw "Bridge did not listen on loopback; inspect $data/bridge.log and scheduled task result." }
$uri = "http://127.0.0.1:$Port/ipp/print"
if ($Mode -eq 'Live' -and $old) {
    # Windows deduplicates an existing IPP endpoint even with a different name.
    # The checked-empty capture queue can retain its native port and be renamed;
    # PAPPL/worker data above is a fresh live queue with no captured jobs.
    Rename-Printer -Name $old.Name -NewName $queueName
} else {
    Add-Printer -Name $queueName -IppURL $uri
}
Get-Printer -Name $queueName | Select-Object Name,DriverName,PortName,PrinterStatus
Write-Output "Mode: $Mode. Layout: $PreparationMode. Local data: $data. No print job was submitted by this installer."
