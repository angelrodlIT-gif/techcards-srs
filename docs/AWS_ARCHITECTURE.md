# ADR: AWS deployment for TechCards SRS

**Status:** Proposed. Design for a single invited learner in one AWS region.
The account, region, domain, and spending ceiling require owner approval before
provisioning. Use synthetic study data throughout the pilot, including
deployment and recovery drills.

## Runtime decision

Use ECS on Fargate with RDS for PostgreSQL 16. The
[Dockerfile](../Dockerfile) already packages a non-root Uvicorn service and
Alembic. [Compose](../compose.yaml) binds the API and PostgreSQL host ports to
loopback and runs migrations before starting the API. Preserve that release
ordering with a one-off ECS migration task and reuse the same image digest for
the service. [Settings](../app/config.py) and [database setup](../app/db.py)
use a PostgreSQL URL by default. The Compose test profile uses SQLite in
memory, so its results cannot establish PostgreSQL or RDS behavior.

Lambda could reduce idle compute for bursty traffic. It would require an ASGI
adapter or a different entry point, separate migration execution, and explicit
concurrency and connection management to protect PostgreSQL. It would still
need the database, authentication, and recovery controls. Fargate preserves
the existing HTTP and migration entry points at the cost of always-on compute
and a load balancer. Start with one API task and one Single-AZ DB instance for
the pilot, accepting downtime during failures. Revisit sizing, Multi-AZ and
Lambda after measuring traffic, DB connections and recovery times.

## Authentication and trust boundaries

- **Client to edge.** Use an API Gateway HTTP API with an ACM-backed HTTPS
  custom domain and a Cognito user pool dedicated to this environment. Disable
  self-registration and provision only the learner. Require MFA and OAuth
  authorization code with PKCE for the interactive client. Require a short-lived
  bearer access token on each published method and path. The JWT authorizer
  checks the configured issuer, app client audience (or client ID under
  API Gateway's rules), expiry and a dedicated API scope. Verify that only the
  invited learner can obtain that scope. Disable the default execute-api URL.
  See the [JWT authorizer contract](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-jwt-authorizer.html).
- **Edge to service.** Publish only `GET /decks`, `GET /study/next`,
  `POST /study/{card_id}/reveal` and `POST /study/{card_id}/grade`. Use
  explicit method and path rules with the JWT authorizer and no catch-all.
  Keep docs, OpenAPI, health, audio and pronunciation off the public route
  map. Account for path rewriting and test the effective route map before
  enabling the custom domain. The [application](../app/main.py) has no caller
  authentication or per-user data isolation. The invited learner can access
  the synthetic study data through the published routes. Adding users requires
  per-user authorization and data ownership first.
- **Inside the VPC.** The gateway connects through a dedicated VPC link to an
  internal ALB over HTTPS with server name verification. The ALB forwards to
  Uvicorn over HTTP on port 8000 inside private subnets. This hop is cleartext
  and depends on VPC isolation and security groups. Allow ALB ingress only from
  the VPC link security group, and API task ingress only from the ALB group.
  Assign no public IPs to tasks. Reserve the ALB security group for the trusted
  integration. See [HTTP API private integrations](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-develop-integrations-private.html).
- **Service to data.** Disable public RDS access. Use a private DB subnet group
  spanning two Availability Zones, allow TCP 5432 only from dedicated API and
  migration task groups, and require TLS with CA and hostname verification
  (`sslmode=verify-full`). Encrypt the instance and backups at rest. Keep DB
  administration on a separately authorized private path. Size connection pools
  and bound task count against the DB connection budget, including deployments.
  Use VPC endpoints for ECR, its S3 image layers, CloudWatch Logs and Secrets
  Manager. Start with no general-purpose internet egress.
- **Release gate.** Before allowing external traffic, demonstrate rejection of
  missing, expired and wrong-issuer, wrong-client or wrong-scope tokens and
  rejection of direct access to the ALB, tasks and RDS from outside their
  allowed sources. With a valid token, verify that excluded routes stay
  unreachable, including encoded or rewritten paths, and that the learner
  can list decks, fetch, reveal and grade a synthetic card. Keep the edge
  disabled if any check fails.

## Data and audio

Preserve the local-only interview-text contract in [Study Loop](STUDY_LOOP.md).
Seed a fresh RDS database with reviewed synthetic decks and cards through a
private, authorized setup step. Exclude real interview answers, personal
details from study content, and imports from local databases or exports.
The [grade handler](../app/main.py) updates scheduling and stores
a review using a numeric grade from [StudyGradeInput](../app/schemas.py).

Keep every method on `/errors` and `/errors/*` private to local use. The
[error handlers](../app/main.py) can save attempted and corrected answers,
and approval can copy that text into a card. The `consent: true` field on
`/errors/suggest` does not authorize cloud storage. Also exclude deck and
card create/update, card generation, source create/update/approval, and
template-to-card creation. The [API handlers](../app/main.py) accept
free-form fields through several of those routes and can persist them
directly or in generated cards. Keep the default offline generator from
[settings](../app/config.py). The optional
[OpenAI-compatible adapter](../app/generator.py) needs separate approval
for outbound traffic and submitted data.

The [audio and pronunciation guard](../app/main.py) requires an ASGI
client host of `127.0.0.1` or `::1`, a request URL hostname of
`127.0.0.1`, `::1` or `localhost`, and absence of both `Forwarded` and
`X-Forwarded-For`. The [local setup](STUDY_LOOP.md) assumes a direct
loopback connection with no reverse proxy and Uvicorn proxy header
processing disabled. The ALB deployment is proxied, so omit listening
audio and all pronunciation routes from its public surface.

Both synthesis endpoints require `Polly-Opt-In: true`. Polly is disabled
by default in [settings](../app/config.py). When enabled, the
[listening service](../app/listening.py) sends reference text to Polly on
cache misses and caches clips in worker RAM. The [upload handler](../app/main.py)
requires `Recording-Consent: true` and can use a PostgreSQL card revision
for cache identity. [Recording bytes](../app/pronunciation.py) stay in
worker RAM with a one-hour TTL and bounded capacity and are lost on restart.

Keep Polly disabled and grant no Polly or audio bucket permissions.
The private S3 audio requirement in [#26](https://github.com/angelrodlIT-gif/techcards-srs/issues/26)
needs reconciliation before provisioning an audio bucket. Any later proposal
for hosted audio must define permitted content, consent, authorization and
deletion before changing the loopback boundary or storing audio objects.

## Roles and secrets

- Give the API DB role only the DML and sequence rights required by the app.
  Use a separate schema-owning DB role for migrations. Keep RDS admin credentials
  out of both task definitions. A migration task uses its own security group
  and can run only through the deployment path.
- Give ECS execution roles only the image pull and log write permissions they
  need, plus read access to their own Secrets Manager secret and decrypt access
  if required for its KMS key. Scope resources where the action supports it.
  The API task role needs no AWS service permissions for the text pilot.
- Inject separate database URLs from Secrets Manager. Keep secret values out
  of Git, image layers, Terraform inputs/state and logs. Provision secret
  references with Terraform and populate values via an authorized separate
  process. Rotate credentials and roll tasks to pick up new values before
  retiring old credentials. Restrict task inspection and shell access.
- Give GitHub deployment a separate short-lived OIDC role scoped to this
  repository and its protected deployment environment, restricted to reviewed
  main by environment rules. Restrict image publication, ECS deployment and
  role passing to the named workload resources. Keep infrastructure provisioning
  in a separate role. Fork PRs get neither deploy credentials nor self-hosted
  execution.

## Cost, logs and recovery

- **Cost.** Before apply, approve a monthly ceiling B for the tagged pilot.
  Configure actual alerts at 50%, 80% and 100% of B and a forecast alert at
  100%. Send alerts to the owner and review the first month weekly. Budget
  notifications can lag and do not cap spending. Set gateway throttles and
  bound ECS scaling and database storage growth. Use regional rates times
  projected usage: task CPU and memory hours plus migration runs, RDS instance
  hours plus storage and billable backup, ALB hours and capacity units, API
  requests, endpoint hours and data, logs and alarms, identity, secrets, DNS,
  and transfer. Compare an idle month and a busy month before approval.
  [AWS Pricing Calculator](https://calculator.aws/) ·
  [AWS Budgets](https://docs.aws.amazon.com/cost-management/latest/userguide/budgets-managing-costs.html)
- **Logs.** Start with 30-day retention for gateway, API and migration logs.
  Record route templates, status, latency and correlation ID. Exclude content,
  raw URLs and query strings, audio, tokens and credentials. Configure log
  access by role and alarm on unhealthy targets, deployment failure, elevated
  5xx and latency, and low DB storage. [/health](../app/main.py) is liveness
  only. Require a separate private DB-backed readiness check and a protected
  end-to-end probe before accepting a release.
- **Backup and DR.** Require 14 days of encrypted RDS point-in-time recovery,
  deletion protection, and a separately retained encrypted snapshot before
  risky migrations or teardown. Review those snapshots at 30 days and expire
  them unless the owner authorizes longer retention. Deleted data can remain
  in backups until retention expires. Propose a same-region RPO of 15 minutes
  and RTO of four hours, subject to a measured drill. Region-wide loss is
  outside the pilot targets. Restore into a new private instance, validate
  Alembic revision, counts, relationships and the study loop before cutover.
  [Local backup runbook](BACKUP_RESTORE.md) supplies validation patterns.
  Roll back the image only if compatible with the live schema. If restoration
  is required, pause writes and account for writes since the restore point
  before switching endpoints.

## Delivery and evidence

| Issue | Responsibility |
| --- | --- |
| #26 | Provision Terraform, protect remote state and secrets, estimate regional costs and verify isolation in the approved environment. Resolve audio scope before creating an audio bucket. |
| [#27](https://github.com/angelrodlIT-gif/techcards-srs/issues/27) | Wire OIDC and publish the image. Run one migration task to success before rolling out that digest. Preserve hosted CI fallback and document schema-compatible rollback. |
| [#28](https://github.com/angelrodlIT-gif/techcards-srs/issues/28) | Prove authenticated access and blocked bypasses, sanitized logs and alarms, disposable restore and study-data integrity, failed-release rollback, cost review and data-safe teardown. Record actual RPO and RTO. |

This ADR records the #25 design. Deployment, IAM and network enforcement,
regional cost estimates and recovery results require later verification.
