# Cost control for the CodeBuild metadata pipeline

The initial pipeline is designed to cost very little:
- one manually started build at a time;
- the smallest on-demand compute;
- a 15-minute hard timeout;
- a few small JSON files.

It is **not free by design**, and nothing in AWS guarantees a spending cap. This page
explains what can cost money and which controls exist.

## Resources and what they cost

| Resource | Persists? | Cost drivers | Created by |
|---|---|---|---|
| CodeBuild project | yes, but idle when not building | **Build minutes** on `BUILD_GENERAL1_SMALL`, billed per build minute, while a build runs. Nothing while idle: no webhook, schedule or reserved capacity | the stack |
| CloudWatch Logs group `/aws/codebuild/<project>` | yes, 7-day retention | Log ingestion and storage (kilobytes per build) | the stack |
| IAM role | yes | none | the stack |
| S3 staging bucket | yes, **already exists** | PUT requests and storage for one small manifest per publishing build. Objects expire after 7 days (existing lifecycle rule) | operator, earlier |
| CodeConnections connection | yes | none known; check current pricing | operator (console) |
| Data transfer | per build | Installing six or seven small Python wheels from PyPI (inbound). Uploading a few KB to S3 in the same Region | – |

What the pipeline avoids, because each would persist or keep running:
- NAT gateways;
- EC2 instances;
- VPC configuration;
- reserved-capacity fleets;
- EFS;
- caches;
- build artifacts;
- privileged or Docker builds;
- scheduled triggers;
- webhooks;
- Lambda functions;
- EventBridge rules;
- container registries.

Lambda compute for CodeBuild is not offered in ap-southeast-3 (verified 2026-10-20), so the
template uses EC2 on-demand compute.

## Expected size of one dry-run build

These figures are estimates, not measurements: no CodeBuild run has happened yet.
- **Locally:** `tools/validate.py all`, the offline test suite (58 tests, about 13 s) and the
  dry-run (under 1 s) together take well under a minute.
- **In CodeBuild:** provisioning the container and installing the hash-locked dependencies
  add to that, so expect **about 2–4 billed minutes** per build.
- **The ceiling:** the 15-minute timeout bounds any single build.

Check the actual duration of the first build in its build details, and record it here.

## Free tier, credits, alerts and hard limits

These four things are often confused:
- **AWS Free Tier for CodeBuild:**
  - The CodeBuild pricing page says the free tier includes *100 total build minutes per
    month with the general1.small or arm1.small instance types* (on-demand EC2).
  - Whether your account gets this depends on the account's free-tier eligibility and plan.
    Check **Billing → Free Tier** in the console.
  - The pricing page did not list ap-southeast-3 per-minute rates when checked; take
    current Jakarta prices from the console or the AWS Pricing Calculator.
- **Promotional credits:**
  - Credits apply only to the services and terms of each credit, and they expire.
  - Check **Billing → Credits** for the services covered. A charge outside a credit's scope
    is billed normally.
  - Do not assume credits cover CodeBuild, CloudWatch or S3 until you have checked.
- **AWS Budgets (the USD 5/month alert):**
  - A budget **sends notifications**; it does not stop builds or delete resources.
  - Billing data arrives with a delay, so an alert can come after the threshold has already
    been passed.
  - Budget actions can apply IAM or SCP policies automatically, but none is configured
    here. Add one only after deciding what it should block.
- **Hard limits that exist in this design:**
  - `TimeoutInMinutes: 15`: CodeBuild stops a build after 15 minutes.
  - `ConcurrentBuildLimit: 1`: a second concurrent build is throttled.
  - No triggers: builds start only when someone runs `start-build`.
  - Log retention of 7 days.
  - The bucket's 7-day lifecycle rule.
  - `max_requests` and `max_run_seconds` in `registry/sources.json` for any future discovery
    run.

## Habits that keep the cost low

- Run `python3 tools/validate.py all` and the offline tests locally before any AWS build.
- Start builds one at a time and only when needed; do not add a webhook or schedule in this
  phase.
- Keep `ENABLE_S3_PUBLISH=false` by default and enable it for one build at a time.
- Look at **Cost Explorer**, filtered by service, after the first builds, and again monthly.
- Delete the stack when the pipeline is not needed ([AWS_SETUP.md](AWS_SETUP.md), step 11).
  The staging bucket and its lifecycle rule are not affected.

## Before adding anything that runs or persists

Write down, in the pull request:
- its purpose;
- whether it persists or runs on a schedule;
- its cost drivers: compute time, requests, storage, data transfer, and per-hour charges
  such as NAT gateways or fleets.

Examples:
- discovery runs against real sources;
- a schedule;
- a GitHub write-back job;
- DumprX extraction. DumprX needs GiB of disk and long runtimes: a separate evaluation, not
  this project.
