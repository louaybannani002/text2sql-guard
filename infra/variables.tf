variable "subscription_id" {
  description = "Azure subscription (Azure for Students)."
  type        = string
}

variable "location" {
  description = "Region of every resource."
  type        = string
  default     = "polandcentral"
}

variable "prefix" {
  description = "Short name used in resource names."
  type        = string
  default     = "t2s"
}

variable "alert_email" {
  description = "Receives the budget alerts (50/80/100%) and the hard-stop notice."
  type        = string
}

variable "budget_amount_usd" {
  description = "Monthly budget; at 100% the automation stops Postgres and every container app."
  type        = number
  default     = 15
}

variable "budget_start_date" {
  description = "First day of the first budget month (RFC 3339, the 1st of a month)."
  type        = string
  default     = "2026-10-01T00:00:00Z"
}

variable "webhook_expiry" {
  description = "Expiry of the hard-stop runbook webhook (at most a year ahead; renew it before)."
  type        = string
  default     = "2027-10-01T00:00:00Z"
}

variable "allow_setup_ip" {
  description = "Open Postgres to this machine's public IP (migrations, data load). Turn off after setup."
  type        = bool
  default     = true
}

variable "aca_outbound_ips" {
  description = "Outbound IPs of the Container Apps (output api_outbound_ips after the first apply)."
  type        = list(string)
  default     = []
}

variable "secrets_version" {
  description = "Bump to rotate the generated passwords and rewrite every Key Vault secret."
  type        = number
  default     = 1
}

variable "api_image" {
  description = "Initial API image; deploy.yml replaces it (Terraform then ignores image changes)."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

variable "web_image" {
  description = "Initial web image; deploy.yml replaces it."
  type        = string
  default     = "mcr.microsoft.com/k8se/quickstart:latest"
}

variable "llm" {
  description = "Model configuration of the API (non-secret)."
  type = object({
    model_main      = string
    model_fast      = string
    model_local     = string
    fallback_main   = string
    fallback_fast   = string
    embedding_model = string
    timeout_s       = number
    free_tier       = list(string)
  })
  default = {
    model_main      = "gemini/gemini-3.5-flash-lite"
    model_fast      = "gemini/gemini-3.5-flash-lite"
    model_local     = "ollama_chat/qwen2.5-coder:7b"
    fallback_main   = "groq/openai/gpt-oss-120b"
    fallback_fast   = "groq/openai/gpt-oss-20b"
    embedding_model = "gemini/gemini-embedding-001"
    timeout_s       = 60
    free_tier       = ["gemini", "groq"]
  }
}

# Provider keys: ephemeral (never in the state or a file), written to Key Vault through
# write-only attributes. Pass them from backend/.env at plan/apply time (docs/deployment.md).
variable "gemini_api_key" {
  type      = string
  sensitive = true
  ephemeral = true
}

variable "groq_api_key" {
  type      = string
  sensitive = true
  ephemeral = true
}

variable "langfuse_public_key" {
  type      = string
  sensitive = true
  ephemeral = true
}

variable "langfuse_secret_key" {
  type      = string
  sensitive = true
  ephemeral = true
}

variable "langfuse_host" {
  type    = string
  default = "https://cloud.langfuse.com"
}
