# Key Vault (RBAC): provider keys from ephemeral variables, generated passwords from ephemeral
# random_password, all written through write-only attributes: no secret value is ever stored
# in the Terraform state. Bump var.secrets_version to rotate them.

resource "azurerm_key_vault" "main" {
  name                       = "kv-${var.prefix}-demo-${local.suffix}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  tenant_id                  = data.azurerm_client_config.current.tenant_id
  sku_name                   = "standard"
  rbac_authorization_enabled = true
  soft_delete_retention_days = 7
  purge_protection_enabled   = false # demo vault: allow a clean destroy after the soft delete
  tags                       = local.tags
}

# Whoever runs Terraform writes the secrets; the apps only read them.
resource "azurerm_role_assignment" "deployer_kv_officer" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets Officer"
  principal_id         = data.azurerm_client_config.current.object_id
}

resource "azurerm_role_assignment" "apps_kv_reader" {
  scope                = azurerm_key_vault.main.id
  role_definition_name = "Key Vault Secrets User"
  principal_id         = azurerm_user_assigned_identity.apps.principal_id
}

ephemeral "random_password" "pg_admin" {
  length  = 32
  special = false # used inside URLs: letters and digits only
}

ephemeral "random_password" "reader" {
  length  = 32
  special = false
}

ephemeral "random_password" "app" {
  length  = 32
  special = false
}

ephemeral "random_password" "redis" {
  length  = 32
  special = false
}

ephemeral "random_password" "jwt" {
  length  = 64
  special = false
}

ephemeral "random_password" "demo" {
  length  = 20
  special = false
}

locals {
  pg_host = azurerm_postgresql_flexible_server.main.fqdn
  db      = azurerm_postgresql_flexible_server_database.text2sql.name
  dsn     = "${local.pg_host}:5432/${local.db}?sslmode=require"
  # name => ephemeral value. The API's DATABASE_URL is the t2s_app URL: the admin URL only
  # goes to the migration job, never to request handling.
  secret_values = {
    "gemini-api-key"      = var.gemini_api_key
    "groq-api-key"        = var.groq_api_key
    "langfuse-public-key" = var.langfuse_public_key
    "langfuse-secret-key" = var.langfuse_secret_key
    "admin-database-url"  = "postgresql+asyncpg://t2sadmin:${ephemeral.random_password.pg_admin.result}@${local.dsn}"
    "reader-database-url" = "postgresql+asyncpg://t2s_reader:${ephemeral.random_password.reader.result}@${local.dsn}"
    "app-database-url"    = "postgresql+asyncpg://t2s_app:${ephemeral.random_password.app.result}@${local.dsn}"
    "redis-password"      = ephemeral.random_password.redis.result
    "redis-url"           = "redis://:${ephemeral.random_password.redis.result}@${local.name}-redis:6379/0"
    "jwt-secret"          = ephemeral.random_password.jwt.result
    "demo-password"       = ephemeral.random_password.demo.result
  }
}

locals {
  # Static names: for_each cannot iterate over a map holding ephemeral values.
  secret_names = [
    "gemini-api-key", "groq-api-key", "langfuse-public-key", "langfuse-secret-key",
    "admin-database-url", "reader-database-url", "app-database-url",
    "redis-password", "redis-url", "jwt-secret", "demo-password",
  ]
}

resource "azurerm_key_vault_secret" "main" {
  for_each         = toset(local.secret_names)
  name             = each.key
  key_vault_id     = azurerm_key_vault.main.id
  value_wo         = local.secret_values[each.key]
  value_wo_version = var.secrets_version
  content_type     = "text/plain"
  depends_on       = [azurerm_role_assignment.deployer_kv_officer]
}
