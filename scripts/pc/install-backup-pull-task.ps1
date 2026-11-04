# Registers (or re-registers) the Windows Task Scheduler entry that runs
# scripts/pc/pull-beta-backups.sh in WSL every night (docs/OPERATIONS.md, "Off-box copies of beta
# backups"). For the current user, no admin rights, no prompts; running it again replaces the
# same task with the same settings.
#
# From WSL:   powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$(wslpath -w ~/src/RouteMaker/scripts/pc/install-backup-pull-task.ps1)"
# Remove:     Unregister-ScheduledTask -TaskPath '\RouteMaker\' -TaskName 'Pull beta backups' -Confirm:$false
#
# When: 04:00 local time (America/New_York). The beta's dump starts at 07:00 UTC
# (config.procrastinate NIGHTLY_BACKUP_CRON) and may take up to 30 minutes: that is 03:00 EDT in
# summer and 02:00 EST in winter, so 04:00 local is 1 h after it in summer and 2 h in winter.
# A PC that is off or asleep at 04:00 runs it as soon as it can (StartWhenAvailable).
# It runs only while the owner is signed in to Windows (an interactive task needs no password).
param(
    [string]$Distro = 'Ubuntu-26.04',
    [string]$Script = '~/src/RouteMaker/scripts/pc/pull-beta-backups.sh',
    [string]$At = '04:00'
)
$ErrorActionPreference = 'Stop'

$taskPath = '\RouteMaker\'
$taskName = 'Pull beta backups'
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name

# Double quotes, not single: Windows passes "..." to wsl.exe as one argument with the quotes
# removed, so bash -lc gets the bare path and expands the ~ itself.
$action = New-ScheduledTaskAction -Execute 'wsl.exe' `
    -Argument "-d $Distro -- bash -lc `"$Script`""
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
Write-Output ("runs: wsl.exe {0}" -f $action.Arguments)
