# Registers (or re-registers) the Windows Task Scheduler entry that runs
# scripts/pc/pull-beta-backups.sh in WSL every night (docs/OPERATIONS.md, "Off-box copies of beta
# backups"). For the current user, no admin rights, no prompts; running it again replaces the
# same task with the same settings.
#
# From WSL:   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w ~/src/RouteMaker/scripts/pc/install-backup-pull-task.ps1)"
# Remove:     Unregister-ScheduledTask -TaskPath '\' -TaskName 'RouteMaker - Pull beta backups' -Confirm:$false
#
# When: 04:00 local time (America/New_York). The beta's dump starts at 07:00 UTC
# (config.procrastinate NIGHTLY_BACKUP_CRON) and may take up to 30 minutes: that is 03:00 EDT in
# summer and 02:00 EST in winter, so 04:00 local is 1 h after it in summer and 2 h in winter.
# A PC that is off or asleep at 04:00 runs it as soon as it can (StartWhenAvailable).
# It runs only while the owner is signed in to Windows (an interactive task needs no password).
#
# It never starts the distro. The distro that serves the home stack starts the stack when it
# boots (scripts/boot/routemaker-boot.service, with linger on), and the stack must not come up
# by itself, so the task first asks Windows which distros are running (`wsl.exe -l --running`,
# which starts none) and, when this one is not, does nothing and ends with result 3. The beta
# reports the copy as stale once no run has worked for 36 h (scripts/beta/alert.sh watch).
param(
    [string]$Distro = 'Ubuntu-26.04',
    [string]$Script = '~/src/RouteMaker/scripts/pc/pull-beta-backups.sh',
    [string]$At = '04:00'
)
$ErrorActionPreference = 'Stop'

$taskPath = '\'  # the root folder: making a new folder can need admin rights
$taskName = 'RouteMaker - Pull beta backups'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# The task runs a short PowerShell command, passed encoded so no quoting is lost on the way: it
# lists the running distros (WSL_UTF8, so the names are not UTF-16) and runs the script only in a
# distro that is already up. bash -lc gets the bare path and expands the ~ itself.
function Quote([string]$s) { "'" + $s.Replace("'", "''") + "'" }
$command = @"
`$env:WSL_UTF8 = '1'
`$running = @(wsl.exe -l --running -q 2>`$null | ForEach-Object { `$_.Replace([string][char]0, '').Trim() } | Where-Object { `$_ })
if (`$running -notcontains $(Quote $Distro)) { exit 3 }
& wsl.exe -d $(Quote $Distro) -- bash -lc $(Quote $Script)
exit `$LASTEXITCODE
"@
$encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -WindowStyle Hidden -EncodedCommand $encoded"
$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskPath $taskPath -TaskName $taskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal `
    -Description 'Copies the beta''s nightly encrypted database dumps (*.dump.age) into Documents\RouteMaker\beta-backups. docs/OPERATIONS.md, "Off-box copies of beta backups".' `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskPath $taskPath -TaskName $taskName
$info = $task | Get-ScheduledTaskInfo
Write-Output ("registered: {0}{1}, daily at {2} local, next run {3}" -f $taskPath, $taskName, $At, $info.NextRunTime)
Write-Output "runs, only while $Distro is already running (otherwise result 3, nothing started):"
Write-Output $command
