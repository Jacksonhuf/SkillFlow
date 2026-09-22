#Requires -Version 5.1
<#
.SYNOPSIS
  Register a Windows Task Scheduler job that runs a universal-browser template on this machine.

.DESCRIPTION
  Per-user local Chrome model: the task runs under the current user account (interactive session)
  so it can reuse the already signed-in Chrome profile. If the target system is logged out, the run
  stops in WAIT_USER_AUTH and the user resumes it from the local console (invoke.py ui) or Agent.

.EXAMPLE
  .\Register-ScheduledRun.ps1 -TemplateId supplier_order_pack -Daily "08:30" -Var @{date="yesterday"}

.EXAMPLE
  .\Register-ScheduledRun.ps1 -TemplateId sales_daily -Daily "07:00" -TaskName "UB-SalesDaily" -Unregister
#>
param(
    [Parameter(Mandatory = $true)][string]$TemplateId,
    [string]$Daily = "08:00",
    [hashtable]$Var = @{},
    [string]$TaskName = "",
    [string]$SkillRoot = "",
    [string]$Python = "py",
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

if (-not $SkillRoot) {
    # <skill root>\scripts\windows\Register-ScheduledRun.ps1
    $SkillRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
    if (-not (Test-Path (Join-Path $SkillRoot "SKILL.md"))) {
        $SkillRoot = (Get-Location).Path
    }
}
$Invoke = Join-Path $SkillRoot "scripts\invoke.py"
if (-not (Test-Path $Invoke)) {
    throw "invoke.py not found under $SkillRoot. Pass -SkillRoot <universal-browser directory>."
}
if (-not $TaskName) { $TaskName = "UniversalBrowser-$TemplateId" }

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Removed scheduled task $TaskName"
    exit 0
}

$varArgs = @()
foreach ($key in $Var.Keys) { $varArgs += "--var `"$key=$($Var[$key])`"" }
$arguments = "`"$Invoke`" run $TemplateId " + ($varArgs -join " ")

$action = New-ScheduledTaskAction -Execute $Python -Argument $arguments -WorkingDirectory $SkillRoot
$trigger = New-ScheduledTaskTrigger -Daily -At $Daily
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Registered $TaskName: daily at $Daily -> $Python $arguments"
Write-Host "Results: $SkillRoot\runs\<run_id>\ ; view them with: $Python `"$Invoke`" ui"
