# Non-secret settings of the demo environment. Secrets (provider keys) are passed as ephemeral
# TF_VAR_* environment variables from backend/.env (docs/deployment.md), never written here.
location          = "polandcentral"
prefix            = "t2s"
budget_amount_usd = 15
budget_start_date = "2026-10-01T00:00:00Z"
allow_setup_ip    = true
aca_outbound_ips  = [] # fill from `terraform output api_outbound_ips` after the first apply
secrets_version   = 1
# subscription_id and alert_email: TF_VAR_subscription_id / TF_VAR_alert_email (not committed)
