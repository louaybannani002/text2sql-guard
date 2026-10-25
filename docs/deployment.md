# Deployment (Azure, demo-only hosting)

The live demo runs on Azure for Students in `polandcentral`, **on demand**: everything scales
to zero or is stopped between demos, every deploy and demo start waits for the owner's approval
in GitHub, and a 15 USD monthly budget triggers an automatic hard stop. Infrastructure is
Terraform in `infra/`; the MONEY RULE in `CLAUDE.md` applies to every step that creates,
starts or changes something in Azure.

## What gets created (`infra/`)

| Resource | Name | Setting | Costs while idle? |
|---|---|---|---|
| Resource group | `rg-t2s-demo` | | no |
| Log Analytics workspace | `log-t2s-demo` | 30-day retention, 0.1 GB/day cap | no (inside the free 5 GB/month) |
| Container Registry | `acrt2sdemo<suffix>` | Basic, admin user off | **yes**, ~0.17 USD/day |
| PostgreSQL Flexible Server | `psql-t2s-demo-<suffix>` | 16, Burstable B1ms, 32 GB P4, no HA, 7-day backups, `azure.extensions=VECTOR`, firewall: Container Apps outbound IPs + the setup IP | **storage yes** (~4.2 USD/month); compute only while started |
| Key Vault | `kv-t2s-demo-<suffix>` | RBAC, soft delete 7 days | ~0 (per operation) |
| User-assigned identity | `id-t2s-demo-apps` | AcrPull + Key Vault Secrets User | no |
| Container Apps environment | `cae-t2s-demo` | Consumption | no |
| Container app `t2s-demo-api` | | min 0 / max 3, HTTP autoscaling, external HTTPS, CORS = the frontend | no at zero replicas (free monthly grant) |
| Container app `t2s-demo-web` | | min 0 / max 2, external HTTPS | no at zero replicas |
| Container app `t2s-demo-redis` | | `redis:7-alpine`, min 0 / max 1, internal TCP only, password from Key Vault, no persistence | no at zero replicas |
| Automation account + runbook + webhook | `aa-t2s-demo`, `stop-demo` | Basic (500 free job minutes/month) | no |
| Action group + budget | `ag-t2s-demo-budget`, `budget-t2s-demo` | 15 USD/month, alerts 50/80/100% | no |
| State storage (bootstrap) | `rg-t2s-tfstate`, `stt2sstate<suffix>` | LRS, Entra ID only, versioning | a few cents/month |

## Expected cost

Estimates from Azure list prices (check the [pricing calculator](https://azure.microsoft.com/pricing/calculator/)
for `polandcentral` before applying):

| Item | Per hour | Per month |
|---|---|---|
| Container Registry Basic | 0.007 USD | ~5.00 USD (always) |
| Postgres storage 32 GB | 0.006 USD | ~4.20 USD (always, also when stopped) |
| Postgres B1ms compute | 0.017 USD **while started** | 12.40 USD if never stopped; ~0.35 USD for 20 demo hours |
| Container Apps (3 apps, scale to zero) | 0 at zero replicas | ~0 (monthly free grant: 180,000 vCPU-s, 360,000 GiB-s, 2 M requests) |
| Log Analytics, Key Vault, Automation, action group, budget, identity | ~0 | ~0 |
| Terraform state storage | ~0 | < 0.05 USD |
| **Total with Postgres stopped between demos** | **~0.013 USD idle, ~0.03 USD during a demo** | **~9-10 USD** (8-12 USD band) |

Azure for Students gives a credit (typically 100 USD for 12 months): about 10 months of this
setup. The subscription has a spending limit, so it stops instead of billing when the credit runs
out.

## First apply (owner approval required)

1. Register the resource providers once (free):
   `az provider register -n Microsoft.App`, then `Microsoft.OperationalInsights`,
   `Microsoft.ContainerRegistry`, `Microsoft.DBforPostgreSQL`, `Microsoft.KeyVault`,
   `Microsoft.ManagedIdentity`, `Microsoft.Automation`, `Microsoft.Insights`,
   `Microsoft.Consumption`, `Microsoft.Storage`.
2. Remote state: `cd infra/bootstrap && terraform init && terraform apply`, then write its
   `backend_hcl` output to `infra/backend.hcl` and `cd .. && terraform init -backend-config=backend.hcl`.
3. Export the inputs (values from `backend/.env`, never written to a file):
   `TF_VAR_subscription_id`, `TF_VAR_alert_email`, `TF_VAR_gemini_api_key`,
   `TF_VAR_groq_api_key`, `TF_VAR_langfuse_public_key`, `TF_VAR_langfuse_secret_key`.
4. `terraform plan -var-file=dev.tfvars -out=demo.tfplan`, review, `terraform apply demo.tfplan`.
5. `terraform output api_outbound_ips`: copy the list into `aca_outbound_ips` in `dev.tfvars`,
   plan and apply again (the Postgres firewall then admits the apps). After the data load set
   `allow_setup_ip = false` and apply.

Secrets: provider keys are **ephemeral** variables and every generated password is an
**ephemeral** `random_password`, written to Key Vault and to the server through write-only
attributes, so no secret value is ever stored in the Terraform state. Rotate them by bumping
`secrets_version`. The apps read them from Key Vault with the managed identity.

## Budget hard stop

At 100% of the monthly budget the action group starts the `stop-demo` runbook: it stops the
Postgres server and stops every container app in the resource group (Container Apps cannot have
`max_replicas = 0`; stopping the app is the equivalent, and no revision can then run or be
woken). Emails go out at 50%, 80% and 100%.

- Budgets run on Cost Management data, which lags by up to ~24 hours: the stop can come a day
  late, hence a budget well below the credit.
- **Undo** (after raising the budget or at the start of the next month):
  `az postgres flexible-server start -g rg-t2s-demo -n <server>` and, for each app,
  `az containerapp start -g rg-t2s-demo -n <app>` (or run demo-up, step 5).
- The runbook's webhook expires on `webhook_expiry` (one year): renew it before that date.

## Known limits

- Container Apps outbound IPs on a Consumption environment can change; rerun step 5 above if the
  API suddenly cannot reach Postgres.
- Redis has no persistence by design (cache and rate-limit counters only).
- Azure restarts a stopped Postgres server after 7 days: the daily `demo-down` schedule (step 5)
  stops it again.
