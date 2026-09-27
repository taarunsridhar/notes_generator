<#
Registers a Windows scheduled task that keeps the rebuild runner (nightly.ps1) going without you: it starts at logon and
re-checks every 30 minutes. If the runner is already going, or was killed (laptop died, window closed, reboot), the next
check starts it again and nightly.ps1's crash recovery repairs whatever the killed session left. When every subject is
complete the check exits silently.

usage (no admin needed; the task runs as you, while you are logged on):
  powershell -ExecutionPolicy Bypass -File _studio\tools\install_task.ps1 [-Usage max|buffer] [-Model auto|opus|sonnet]
  powershell -ExecutionPolicy Bypass -File _studio\tools\install_task.ps1 -Remove
  Get-ScheduledTask term2-rebuild | Get-ScheduledTaskInfo         # last / next run and result
#>
param(
  [ValidateSet("buffer", "max")][string]$Usage = "max",
  [ValidateSet("auto", "opus", "sonnet")][string]$Model = "auto",
  [int]$EveryMinutes = 30,
  [switch]$Remove
)
$name = "term2-rebuild"
if ($Remove) {
  Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
  Write-Host "removed $name (a runner already going keeps going until it finishes or you stop it)"
  return
}
$script = (Resolve-Path (Join-Path $PSScriptRoot "nightly.ps1")).Path
$argLine = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$script`" -UntilDone -Model $Model -Usage $Usage -Scheduled"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine -WorkingDirectory (Split-Path (Split-Path $PSScriptRoot))
$triggers = @(
  (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME),
  (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes $EveryMinutes) -RepetitionDuration (New-TimeSpan -Days 3650))
)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 30) -WakeToRun
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $triggers -Settings $settings -Principal $principal `
  -Description "term2 rebuild runner: starts at logon and every $EveryMinutes min; no-op while one is running or when all subjects are complete" -Force | Out-Null
Write-Host "installed ${name}: nightly.ps1 -UntilDone -Model $Model -Usage $Usage, at logon and every $EveryMinutes min"
Write-Host "watch it: Get-Content _studio\logs\$(Get-Date -Format yyyy-MM-dd)\run.log -Wait"
Write-Host "remove it: powershell -ExecutionPolicy Bypass -File _studio\tools\install_task.ps1 -Remove"
