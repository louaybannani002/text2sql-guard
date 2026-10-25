# Budget with a real hard stop. Alerts by email at 50/80/100% of the monthly amount; at 100% the
# action group also starts the stop-demo runbook (Azure Automation, Basic: 500 free job
# minutes a month), which stops Postgres and every container app in the resource group.
# Budgets are evaluated on Cost Management data, which lags by up to ~24 h: the stop is late
# by that much, hence an amount well under the credit. Undo: docs/deployment.md.

resource "azurerm_automation_account" "stop" {
  name                = "aa-${local.name}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku_name            = "Basic"
  tags                = local.tags

  identity {
    type = "SystemAssigned"
  }
}

# Stop rights on this resource group only.
resource "azurerm_role_assignment" "stop_contributor" {
  scope                = azurerm_resource_group.main.id
  role_definition_name = "Contributor"
  principal_id         = azurerm_automation_account.stop.identity[0].principal_id
}

resource "azurerm_automation_variable_string" "resource_group" {
  name                    = "ResourceGroupName"
  resource_group_name     = azurerm_resource_group.main.name
  automation_account_name = azurerm_automation_account.stop.name
  value                   = azurerm_resource_group.main.name
}

resource "azurerm_automation_variable_string" "subscription" {
  name                    = "SubscriptionId"
  resource_group_name     = azurerm_resource_group.main.name
  automation_account_name = azurerm_automation_account.stop.name
  value                   = var.subscription_id
}

resource "azurerm_automation_runbook" "stop" {
  name                    = "stop-demo"
  location                = azurerm_resource_group.main.location
  resource_group_name     = azurerm_resource_group.main.name
  automation_account_name = azurerm_automation_account.stop.name
  runbook_type            = "PowerShell"
  log_progress            = true
  log_verbose             = false
  description             = "Budget hard stop: stop PostgreSQL and every container app."
  content                 = file("${path.module}/runbooks/stop-demo.ps1")
  tags                    = local.tags
}

resource "azurerm_automation_webhook" "stop" {
  name                    = "budget-hard-stop"
  resource_group_name     = azurerm_resource_group.main.name
  automation_account_name = azurerm_automation_account.stop.name
  runbook_name            = azurerm_automation_runbook.stop.name
  expiry_time             = var.webhook_expiry
  enabled                 = true
}

resource "azurerm_monitor_action_group" "budget" {
  name                = "ag-${local.name}-budget"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "t2sbudget"
  tags                = local.tags

  email_receiver {
    name          = "owner"
    email_address = var.alert_email
  }

  automation_runbook_receiver {
    name                    = "hard-stop"
    automation_account_id   = azurerm_automation_account.stop.id
    runbook_name            = azurerm_automation_runbook.stop.name
    webhook_resource_id     = azurerm_automation_webhook.stop.id
    service_uri             = azurerm_automation_webhook.stop.uri
    is_global_runbook       = false
    use_common_alert_schema = true
  }
}

resource "azurerm_consumption_budget_resource_group" "monthly" {
  name              = "budget-${local.name}"
  resource_group_id = azurerm_resource_group.main.id
  amount            = var.budget_amount_usd
  time_grain        = "Monthly"

  time_period {
    start_date = var.budget_start_date
  }

  notification {
    enabled        = true
    threshold      = 50
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    threshold      = 80
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
  }

  notification {
    enabled        = true
    threshold      = 100
    operator       = "GreaterThanOrEqualTo"
    threshold_type = "Actual"
    contact_emails = [var.alert_email]
    contact_groups = [azurerm_monitor_action_group.budget.id] # starts the hard stop
  }
}
