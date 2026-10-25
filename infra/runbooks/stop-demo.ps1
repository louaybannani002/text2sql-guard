<#
  Budget hard stop for the text2sql-guard demo (Azure Automation, PowerShell 5.1 runtime).
  Started by the budget's action group at 100% of the monthly amount. With the account's
  system-assigned identity (Contributor on the resource group only) it:
    1. stops the PostgreSQL flexible server (compute billing stops; storage remains);
    2. stops every container app in the resource group (no revision can run or be woken).
  Undo: see docs/deployment.md, "Budget hard stop" (start the server and the apps again).
#>
param([object] $WebhookData)

$ErrorActionPreference = "Stop"
$ResourceGroup = Get-AutomationVariable -Name "ResourceGroupName"
$Subscription = Get-AutomationVariable -Name "SubscriptionId"

Connect-AzAccount -Identity | Out-Null
Set-AzContext -Subscription $Subscription | Out-Null
$base = "/subscriptions/$Subscription/resourceGroups/$ResourceGroup/providers"

$servers = Invoke-AzRestMethod -Method GET -Path "$base/Microsoft.DBforPostgreSQL/flexibleServers?api-version=2024-08-01"
foreach ($server in ($servers.Content | ConvertFrom-Json).value) {
    Write-Output "Stopping PostgreSQL server $($server.name) (state: $($server.properties.state))"
    if ($server.properties.state -eq "Ready") {
        Invoke-AzRestMethod -Method POST -Path "$($server.id)/stop?api-version=2024-08-01" | Out-Null
    }
}

$apps = Invoke-AzRestMethod -Method GET -Path "$base/Microsoft.App/containerApps?api-version=2024-03-01"
foreach ($app in ($apps.Content | ConvertFrom-Json).value) {
    Write-Output "Stopping container app $($app.name)"
    Invoke-AzRestMethod -Method POST -Path "$($app.id)/stop?api-version=2024-03-01" | Out-Null
}
Write-Output "Hard stop done."
