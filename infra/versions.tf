terraform {
  required_version = ">= 1.11" # write-only attributes keep secrets out of the state

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 5.11"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.9"
    }
    http = {
      source  = "hashicorp/http"
      version = "~> 3.6"
    }
  }

  # Remote state in Azure Storage (Entra ID auth, no access keys). Values in backend.hcl, created
  # once by infra/bootstrap (see docs/deployment.md): terraform init -backend-config=backend.hcl
  backend "azurerm" {}
}

provider "azurerm" {
  features {
    key_vault {
      purge_soft_delete_on_destroy = false
    }
    resource_group {
      prevent_deletion_if_contains_resources = true
    }
  }
  subscription_id                 = var.subscription_id
  storage_use_azuread             = true
  resource_provider_registrations = "none" # register providers explicitly, never as a side effect
}
