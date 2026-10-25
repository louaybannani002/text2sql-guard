output "resource_group" {
  value = azurerm_resource_group.main.name
}

output "frontend_url" {
  value = "https://${azurerm_container_app.web.ingress[0].fqdn}"
}

output "api_url" {
  value = "https://${azurerm_container_app.api.ingress[0].fqdn}"
}

output "postgres_server_name" {
  value = azurerm_postgresql_flexible_server.main.name
}

output "postgres_fqdn" {
  value = azurerm_postgresql_flexible_server.main.fqdn
}

output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "key_vault_name" {
  value = azurerm_key_vault.main.name
}

output "apps_identity_id" {
  value = azurerm_user_assigned_identity.apps.id
}

# Copy into aca_outbound_ips (dev.tfvars) after the first apply, then apply again: the API's
# outbound IPs are only known once it exists.
output "api_outbound_ips" {
  value = azurerm_container_app.api.outbound_ip_addresses
}
