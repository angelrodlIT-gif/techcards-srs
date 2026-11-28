# Private PostgreSQL foundation

This Terraform root implements the first slice of [the AWS ADR](../../docs/AWS_ARCHITECTURE.md).
It uses one Single-AZ PostgreSQL 16 instance and two isolated database subnets
in different Availability Zones ([Runtime decision](../../docs/AWS_ARCHITECTURE.md#runtime-decision)
and [Authentication and trust boundaries](../../docs/AWS_ARCHITECTURE.md#authentication-and-trust-boundaries)).
There are no internet routes. PostgreSQL accepts traffic only from the
dedicated future API and migration security groups. Keep group attachment
restricted to those workloads and preserve the AZ list order across runs.
The fixed pilot CIDR is `10.26.0.0/16`. Check overlap before connecting other
networks. Confirm regional support for the assumed `db.t4g.micro` instance and
20 GiB of gp3 storage. Storage autoscaling is disabled.

RDS enforces TLS and manages its master password in Secrets Manager. Terraform
stores the secret reference. Future DB clients must use `sslmode=verify-full`
with the RDS CA and endpoint hostname. The separately authorized private
admin path, API and migration DB roles and URL secrets, and workload IAM are
follow-up work. See [Roles and secrets](../../docs/AWS_ARCHITECTURE.md#roles-and-secrets).

ECS/Fargate, private endpoints, the authenticated edge, CloudWatch logging and
alarms, and budget alerts are follow-ups. The future edge must publish only
the four routes listed in the ADR. Keep `/errors`, audio and pronunciation
local. The audio bucket and Polly permissions remain deferred under
[Data and audio](../../docs/AWS_ARCHITECTURE.md#data-and-audio).

## Local checks

From this directory, use Terraform 1.10 or later in the 1.x series.

```sh
terraform fmt -check
terraform init -backend=false
terraform validate
```

## Plan and apply after owner approval

Approve the account, region, AZs and monthly ceiling before provisioning. Set
the ADR's actual-spend alerts at 50%, 80% and 100% of the ceiling and a forecast
alert at 100%. Use synthetic data only.

An administrator must bootstrap a separate private, versioned S3 state bucket
with public access blocked, TLS enforced and default KMS encryption. Supply
its `bucket`, `region`, environment-specific `key`, `kms_key_id` and
`allowed_account_ids` (a one-element list) in an ignored `pilot.tfbackend` file. Give the provisioning identity access
only to that state prefix, its object and lock file, and the relevant KMS key.
Follow the [S3 backend permissions](https://developer.hashicorp.com/terraform/language/backend/s3#permissions-required).
Use short-lived credentials outside Terraform configuration. Keep the backend
outside this stack's lifecycle.

In a fresh working directory at the reviewed revision, set the five inputs in
an ignored `pilot.tfvars` file. Reserve an unused final snapshot identifier.
Pin and review the resolved provider lock file before deployment. With the
approved provisioning identity, run and review the plan before applying it.
Keep saved plans, state and backend metadata private.

```sh
terraform init -backend-config=pilot.tfbackend
terraform plan -var-file=pilot.tfvars -out=pilot.tfplan
terraform apply pilot.tfplan
```

Verify account and region, state encryption and locking, subnet routes,
security group isolation, public access settings, TLS enforcement, encryption,
backup retention and deletion protection in the chosen environment. Exercise
DB connectivity from the approved private paths when they exist. The ADR
requires a restore drill before relying on its recovery targets.

## Retention, teardown and costs

RDS keeps 14 days of point-in-time recovery during operation. Before teardown,
stop writers and take a separately retained encrypted snapshot. Confirm the
snapshot is available and restorable, then approve and apply a reviewed change
to disable deletion protection. Keep the final snapshot enabled and confirm
its identifier is unused. Review a destroy plan before applying it.

```sh
terraform plan -destroy -var-file=pilot.tfvars -out=teardown.tfplan
terraform apply teardown.tfplan
```

Confirm final snapshot availability and review retained snapshots at 30 days.
Expire them unless the owner approves longer retention. Retain backend object
versions under the state's separate retention policy.

For the first slice, estimate roughly 730 instance hours per month, 20 GiB of
gp3 storage, billable backup and snapshot storage, one managed secret, and
state bucket storage, requests and KMS usage. Apply regional rates and include
retained snapshots after teardown. The full pilot estimate must also include
the runtime, endpoints, edge and observability listed in
[Cost, logs and recovery](../../docs/AWS_ARCHITECTURE.md#cost-logs-and-recovery).
Compare idle and busy months using the [AWS Pricing Calculator](https://calculator.aws/).
Dollar totals depend on the approved region and expected usage.
