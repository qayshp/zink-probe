# Run in PowerShell as the Windows user who paired the printer (administrator).
# Capture is the safe default. Live mode makes a subsequent application Print
# action consume paper. Installation itself never submits a print job.
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$NativeDirectory,
    [Parameter(Mandatory=$true)][string]$Wheel,
    [Parameter(Mandatory=$true)][string]$Python,
    [ValidateSet('Capture','Live')][string]$Mode = 'Capture',
    [string]$DeviceConfig,
    [string]$Root = (Join-Path $env:LOCALAPPDATA 'ZinkProbe'),
    [int]$Port = 8631
)
$ErrorActionPreference = 'Stop'
$taskName = 'ZinkProbe-Select'
$queueName = if ($Mode -eq 'Live') { 'HP Sprocket Select' } else { 'HP Sprocket Select (capture)' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run this installation as administrator, using the account that paired the Select.' }
if ($Root.Contains('"') -or $Root -match '[^\x20-\x7E]') { throw 'This initial Windows package requires an ASCII installation path without quotes.' }
$data = Join-Path $Root $Mode.ToLowerInvariant()
if (Test-Path $data) { throw "The $Mode data directory already exists. Preserve it; this installer does not overwrite jobs or repeat an activation." }
if (Get-Printer -Name $queueName -ErrorAction SilentlyContinue) { throw "Printer already exists: $queueName" }
if ($Mode -eq 'Live') {
    if (!$DeviceConfig) { throw 'Live mode requires a private device.json with paired address and device_id.' }
    $device = Get-Content $DeviceConfig -Raw | ConvertFrom-Json
    if ($device.address -notmatch '^([0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}$' -or $device.device_id -notmatch '^[0-9a-fA-F]{32}$') { throw 'Invalid private device identity.' }
    $old = Get-Printer -Name 'HP Sprocket Select (capture)' -ErrorAction SilentlyContinue
    if ($old -and @(Get-PrintJob -PrinterName $old.Name).Count) { throw 'Finish or cancel all capture queue jobs before activating.' }
    $capture = Join-Path $Root 'capture'
    if (@(Get-ChildItem "$capture/incoming/*.rgb" -ErrorAction SilentlyContinue).Count) { throw 'Unresolved capture rasters remain; inspect them before activation.' }
    foreach ($claim in Get-ChildItem "$capture/jobs/*/claim.json" -ErrorAction SilentlyContinue) {
        $resultPath = Join-Path $claim.DirectoryName 'result.json'
        if (!(Test-Path $resultPath) -or (Get-Content $resultPath -Raw | ConvertFrom-Json).state -ne 'captured') { throw 'An unresolved capture worker exists; inspect it before activation.' }
    }
}
if (!(Test-Path $Root)) {
    New-Item -ItemType Directory $Root | Out-Null
    & icacls $Root /inheritance:r /grant:r "*$($identity.User.Value):(OI)(CI)F" '*S-1-5-18:(OI)(CI)F' '*S-1-5-32-544:(OI)(CI)F' | Out-Null
    if ($LASTEXITCODE) { throw 'Could not restrict the private installation directory.' }
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
$config = @{schema=1; mode=$Mode.ToLowerInvariant(); data_dir=$data; transport='auto'}
if ($Mode -eq 'Live') {
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
Write-Output "Mode: $Mode. Local data: $data. No print job was submitted by this installer."
