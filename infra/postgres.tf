# PostgreSQL Flexible Server 16, Burstable B1ms, 32 GB, no HA. Stopped between demos
# (demo-up / demo-down); Azure restarts a stopped server after 7 days, hence the daily demo-down.

resource "azurerm_postgresql_flexible_server" "main" {
  name                              = "psql-${local.name}-${local.suffix}"
  location                          = azurerm_resource_group.main.location
  resource_group_name               = azurerm_resource_group.main.name
  version                           = "16"
  sku_name                          = "B_Standard_B1ms"
  storage_mb                        = 32768
  storage_tier                      = "P4"
  auto_grow_enabled                 = false
  backup_retention_days             = 7
  geo_redundant_backup_enabled      = false
  public_network_access_enabled     = true # restricted by the firewall rules below
  administrator_login               = "t2sadmin"
  administrator_password_wo         = ephemeral.random_password.pg_admin.result
  administrator_password_wo_version = var.secrets_version
  tags                              = local.tags

  authentication {
    password_auth_enabled = true
  }

  lifecycle {
    ignore_changes = [zone] # chosen by Azure
  }
}

# pgvector must be allow-listed before migration 0007 can CREATE EXTENSION vector.
resource "azurerm_postgresql_flexible_server_configuration" "extensions" {
  name      = "azure.extensions"
  server_id = azurerm_postgresql_flexible_server.main.id
  value     = "VECTOR"
}

resource "azurerm_postgresql_flexible_server_database" "text2sql" {
  name      = "text2sql"
  server_id = azurerm_postgresql_flexible_server.main.id
  charset   = "UTF8"
  collation = "en_US.utf8"
}

data "http" "my_ip" {
  count = var.allow_setup_ip ? 1 : 0
  url   = "https://api.ipify.org"
}

locals {
  firewall_ips = merge(
    { for i, ip in var.aca_outbound_ips : "aca-${i}" => ip },
    var.allow_setup_ip ? { setup = chomp(data.http.my_ip[0].response_body) } : {},
  )
}

resource "azurerm_postgresql_flexible_server_firewall_rule" "allowed" {
  for_each         = local.firewall_ips
  name             = each.key
  server_id        = azurerm_postgresql_flexible_server.main.id
  start_ip_address = each.value
  end_ip_address   = each.value
}
