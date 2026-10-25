# Consumption Container Apps environment with three apps, all scaled to zero when idle.
# Images are set once here (a placeholder) and then owned by deploy.yml.

resource "azurerm_container_app_environment" "main" {
  name                       = "cae-${local.name}"
  location                   = azurerm_resource_group.main.location
  resource_group_name        = azurerm_resource_group.main.name
  log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  tags                       = local.tags
}

locals {
  web_app_name = "${local.name}-web"
  web_origin   = "https://${local.web_app_name}.${azurerm_container_app_environment.main.default_domain}"
  kv_secret    = { for name in local.secret_names : name => azurerm_key_vault_secret.main[name].versionless_id }
  # API settings that are not secret (secrets come from Key Vault below).
  api_env = {
    APP_ENV                 = "production"
    LOG_LEVEL               = "INFO"
    API_HOST                = "0.0.0.0"
    DEMO_USERNAME           = "demo"
    CORS_ALLOWED_ORIGINS    = jsonencode([local.web_origin]) # the frontend only
    LLM_MODEL_MAIN          = var.llm.model_main
    LLM_MODEL_FAST          = var.llm.model_fast
    LLM_MODEL_LOCAL         = var.llm.model_local
    LLM_FALLBACK_MAIN       = var.llm.fallback_main
    LLM_FALLBACK_FAST       = var.llm.fallback_fast
    LLM_EMBEDDING_MODEL     = var.llm.embedding_model
    LLM_TIMEOUT_S           = tostring(var.llm.timeout_s)
    LLM_FREE_TIER_PROVIDERS = jsonencode(var.llm.free_tier)
    LANGFUSE_HOST           = var.langfuse_host
    LANGFUSE_ENABLED        = "true"
  }
  # env var => Key Vault secret name
  api_secret_env = {
    DATABASE_URL        = "app-database-url" # not the admin URL: the API never migrates
    READER_DATABASE_URL = "reader-database-url"
    APP_DATABASE_URL    = "app-database-url"
    REDIS_URL           = "redis-url"
    GEMINI_API_KEY      = "gemini-api-key"
    GROQ_API_KEY        = "groq-api-key"
    LANGFUSE_PUBLIC_KEY = "langfuse-public-key"
    LANGFUSE_SECRET_KEY = "langfuse-secret-key"
    JWT_SECRET          = "jwt-secret"
    DEMO_PASSWORD       = "demo-password"
  }
}

resource "azurerm_container_app" "redis" {
  name                         = "${local.name}-redis"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  secret {
    name                = "redis-password"
    key_vault_secret_id = local.kv_secret["redis-password"]
    identity            = azurerm_user_assigned_identity.apps.id
  }

  # Internal TCP only: reachable as <name>:6379 inside the environment, never from outside.
  ingress {
    external_enabled = false
    transport        = "tcp"
    target_port      = 6379
    exposed_port     = 6379
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 1
    container {
      name   = "redis"
      image  = "docker.io/library/redis:7-alpine"
      cpu    = 0.25
      memory = "0.5Gi"
      # Cache and rate limits only: no persistence (--save "" --appendonly no).
      command = ["sh", "-c", "exec redis-server --requirepass \"$REDIS_PASSWORD\" --save '' --appendonly no"]
      env {
        name        = "REDIS_PASSWORD"
        secret_name = "redis-password"
      }
    }
    tcp_scale_rule {
      name                = "connections"
      concurrent_requests = "10"
    }
  }

  depends_on = [azurerm_role_assignment.apps_kv_reader]
}

resource "azurerm_container_app" "api" {
  name                         = "${local.name}-api"
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  dynamic "secret" {
    for_each = toset(values(local.api_secret_env))
    content {
      name                = secret.value
      key_vault_secret_id = local.kv_secret[secret.value]
      identity            = azurerm_user_assigned_identity.apps.id
    }
  }

  ingress {
    external_enabled = true # the browser calls the API directly (HTTPS only)
    target_port      = 8000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 3
    container {
      name   = "api"
      image  = var.api_image
      cpu    = 0.5
      memory = "1Gi"
      dynamic "env" {
        for_each = local.api_env
        content {
          name  = env.key
          value = env.value
        }
      }
      dynamic "env" {
        for_each = local.api_secret_env
        content {
          name        = env.key
          secret_name = env.value
        }
      }
      # /healthz only: /readyz reports a stopped database as 503 to the frontend (sleeping page),
      # which must still reach the API to show it.
      liveness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/healthz"
      }
      readiness_probe {
        transport = "HTTP"
        port      = 8000
        path      = "/healthz"
      }
    }
    http_scale_rule {
      name                = "http"
      concurrent_requests = "10"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image] # owned by deploy.yml
  }

  depends_on = [azurerm_role_assignment.apps_acr_pull, azurerm_role_assignment.apps_kv_reader]
}

resource "azurerm_container_app" "web" {
  name                         = local.web_app_name
  container_app_environment_id = azurerm_container_app_environment.main.id
  resource_group_name          = azurerm_resource_group.main.name
  revision_mode                = "Single"
  tags                         = local.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.apps.id]
  }

  registry {
    server   = azurerm_container_registry.main.login_server
    identity = azurerm_user_assigned_identity.apps.id
  }

  ingress {
    external_enabled = true
    target_port      = 3000
    transport        = "auto"
    traffic_weight {
      latest_revision = true
      percentage      = 100
    }
  }

  template {
    min_replicas = 0
    max_replicas = 2
    container {
      name   = "web"
      image  = var.web_image
      cpu    = 0.25
      memory = "0.5Gi"
    }
    http_scale_rule {
      name                = "http"
      concurrent_requests = "20"
    }
  }

  lifecycle {
    ignore_changes = [template[0].container[0].image]
  }

  depends_on = [azurerm_role_assignment.apps_acr_pull]
}
