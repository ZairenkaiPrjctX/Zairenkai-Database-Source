# AWS setup: first manual dry-run build

This guide deploys the pipeline described in [AWS_PIPELINE.md](AWS_PIPELINE.md) and runs one
manual dry-run build. Nothing in this repository runs these commands for you:
- **Read-only steps:** 1–5, 7, 9 and 10 only read.
- **Changes to the AWS account:** step 3 (creating the connection), step 6 (executing the
  change set) and step 8 (starting a build). Each needs an explicit decision by the operator.

Read [COST_CONTROL.md](COST_CONTROL.md) first.

Values used below (replace them where yours differ):

```bash
export AWS_REGION=ap-southeast-3                       # Asia Pacific (Jakarta)
export BUCKET=zairenkai-firmware-staging-20261020-x7k9  # existing staging bucket
export PREFIX=staging/
export STACK=zairenkai-database-source-dryrun
export PROJECT=zairenkai-database-source-dryrun
export CONNECTION_REGION=ap-southeast-1                # see step 3
```

Use an IAM Identity Center or IAM user session with the permissions these steps need. Do not
create long-term access keys for this, and never put credentials in this repository.

## 1. Verify the account and Region

```bash
aws sts get-caller-identity --query Account --output text
export ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
aws account get-region-opt-status --region-name "$AWS_REGION"   # expect ENABLED or ENABLED_BY_DEFAULT
```

ap-southeast-3 is an opt-in Region. If it is not enabled, stop here.

## 2. Verify the existing staging bucket (do not recreate it)

```bash
aws s3api get-bucket-location --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID"
aws s3api get-public-access-block --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID"
aws s3api get-bucket-ownership-controls --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID"
aws s3api get-bucket-encryption --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID"
aws s3api get-bucket-versioning --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID"
aws s3api get-bucket-lifecycle-configuration --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID"
```

Expected results:
- **Location:** `ap-southeast-3`.
- **Public access block:** all four settings `true`.
- **Ownership:** `BucketOwnerEnforced`.
- **Encryption:** `AES256`, which is SSE-S3.
- **Versioning:** empty output, or `Suspended`.
- **Lifecycle:** a rule for prefix `staging/` that expires current objects after 7 days, and
  aborts incomplete multipart uploads after 1 day.

If any result differs, stop and resolve the discrepancy first. The template assumes these
settings and does not change them.

## 3. Create and authorize the GitHub connection

**AWS CodeConnections has no endpoint in ap-southeast-3.** This was checked on 2026-10-20
against the AWS General Reference endpoint table. CodeBuild supports cross-Region
connections, but a connection created in an opt-in Region cannot be used in other Regions.
Create the connection in a non-opt-in Region near Jakarta, for example `ap-southeast-1`
(Singapore).

That a Jakarta project can use a Singapore connection is documented but **not yet tested**
here. The first build in step 8 confirms it.

Steps:
1. Sign in to the console as a user who can install GitHub Apps on the `ZairenkaiPrjctX`
   organization, or ask an organization owner to approve the app.
2. Switch the console Region to `ap-southeast-1`.
3. Open **Developer Tools → Settings → Connections**
   (https://console.aws.amazon.com/codesuite/settings/connections) and choose
   **Create connection**.
4. Choose **GitHub**, then name the connection, for example `zairenkai-github`.
5. Choose **Connect to GitHub**, then **Install a new app**, or select the existing
   **AWS Connector for GitHub** installation.
6. Grant it access only to `ZairenkaiPrjctX/Zairenkai-Database-Source`: choose
   **Only select repositories**.
7. Choose **Connect**. The connection status must change from `PENDING` to `AVAILABLE`.

A connection created through the CLI or CloudFormation stays `PENDING` until this console
handshake is completed.

## 4. Get the connection ARN

```bash
aws codeconnections list-connections --region "$CONNECTION_REGION" --provider-type-filter GitHub \
  --query 'Connections[].{name:ConnectionName,status:ConnectionStatus,arn:ConnectionArn}'
export CONNECTION_ARN=arn:aws:codeconnections:ap-southeast-1:<account>:connection/<id>   # copy, do not guess
aws codeconnections get-connection --region "$CONNECTION_REGION" --connection-arn "$CONNECTION_ARN" \
  --query Connection.ConnectionStatus   # must be "AVAILABLE"
```

Older connections have `arn:aws:codestar-connections:...` ARNs. Use
`aws codestar-connections ...` for those; the template accepts both forms.

## 5. Review the template and its permissions

```bash
aws cloudformation validate-template --region "$AWS_REGION" \
  --template-body file://infra/cloudformation/codebuild.yml
```

The stack creates exactly three resources (see the security section of
[SECURITY.md](SECURITY.md#aws-codebuild-metadata-pipeline)):
- **Service role `${ProjectName}-codebuild`:**
  - trust is limited to `codebuild.amazonaws.com`, for this project's ARN in this account
    only;
  - `logs:CreateLogStream` and `logs:PutLogEvents` on its own log group;
  - `s3:PutObject` on `arn:aws:s3:::<bucket>/<prefix>runs/*`, and only when the bucket
    belongs to this account;
  - `GetConnection` and `GetConnectionToken` on the one connection ARN.
  - It has no `s3:ListBucket`, no wildcard actions and no managed policies.
- **Log group `/aws/codebuild/${ProjectName}`:** 7-day retention, deleted with the stack.
- **CodeBuild project:**
  - `BUILD_GENERAL1_SMALL` with an Amazon Linux 2023 image;
  - 15-minute timeout and one concurrent build;
  - no webhook, no artifacts, no cache, no privileged mode, and no build status reported to
    GitHub;
  - `ENABLE_S3_PUBLISH` set to `false`.

It creates no bucket, VPC, NAT gateway, EC2 instance, fleet, schedule or webhook.

## 6. Deploy (only after explicit approval)

Create a change set and read it before executing:

```bash
aws cloudformation create-change-set --region "$AWS_REGION" --stack-name "$STACK" \
  --change-set-name initial --change-set-type CREATE \
  --template-body file://infra/cloudformation/codebuild.yml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameters \
    ParameterKey=GitHubRepositoryUrl,ParameterValue=https://github.com/ZairenkaiPrjctX/Zairenkai-Database-Source.git \
    ParameterKey=CodeConnectionArn,ParameterValue="$CONNECTION_ARN" \
    ParameterKey=SourceBranch,ParameterValue=dev \
    ParameterKey=StagingBucketName,ParameterValue="$BUCKET" \
    ParameterKey=StagingPrefix,ParameterValue="$PREFIX"
aws cloudformation describe-change-set --region "$AWS_REGION" --stack-name "$STACK" --change-set-name initial \
  --query 'Changes[].ResourceChange.{action:Action,type:ResourceType,id:LogicalResourceId}'
# Expect three "Add" rows: AWS::Logs::LogGroup, AWS::IAM::Role, AWS::CodeBuild::Project.
aws cloudformation execute-change-set --region "$AWS_REGION" --stack-name "$STACK" --change-set-name initial
aws cloudformation wait stack-create-complete --region "$AWS_REGION" --stack-name "$STACK"
```

The repository URL above comes from this checkout's `origin` remote. Confirm it is the
repository you mean to build. `SourceBranch` is the branch built when `start-build` names
none. The pipeline files exist only on branches that contain this change.

## 7. Confirm the project configuration (webhook must stay disabled)

```bash
aws codebuild batch-get-projects --region "$AWS_REGION" --names "$PROJECT" --query 'projects[0].{
  webhook: webhook, source: source.type, auth: source.auth.type, reportStatus: source.reportBuildStatus,
  privileged: environment.privilegedMode, compute: environment.computeType, image: environment.image,
  timeout: timeoutInMinutes, concurrency: concurrentBuildLimit, artifacts: artifacts.type,
  env: environment.environmentVariables}'
```

Expected values:
- `webhook`: `null`;
- `privileged`: `false`;
- `concurrency`: `1`;
- `artifacts`: `NO_ARTIFACTS`;
- `ENABLE_S3_PUBLISH`: `false`.

## 8. Start one manual dry-run build

Without publishing:

```bash
BUILD_ID=$(aws codebuild start-build --region "$AWS_REGION" --project-name "$PROJECT" \
  --source-version <branch-with-the-pipeline> --query build.id --output text)
aws codebuild batch-get-builds --region "$AWS_REGION" --ids "$BUILD_ID" \
  --query 'builds[0].{status:buildStatus,phase:currentPhase}'
```

To publish the test manifest from one build, deliberately:

```bash
BUILD_ID=$(aws codebuild start-build --region "$AWS_REGION" --project-name "$PROJECT" \
  --source-version <branch-with-the-pipeline> \
  --environment-variables-override name=ENABLE_S3_PUBLISH,value=true,type=PLAINTEXT \
  --query build.id --output text)
```

## 9. Inspect logs and the S3 object

```bash
aws logs tail "/aws/codebuild/$PROJECT" --region "$AWS_REGION" --since 1h
aws s3api head-object --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID" \
  --key "${PREFIX}runs/${BUILD_ID//:/-}/manifest.json"     # only if publishing was enabled
```

What a successful build shows:
- the log has `pipeline schemas, registry and fixture: OK`, the unittest result, the
  one-line ingest summary with `"status": "ok"`, and `manifest ...: OK`;
- the publish line reads `S3 publish disabled ...`, or `uploaded manifest to s3://...`
  when publishing was enabled.

The build id `<project>:<uuid>` becomes `<project>-<uuid>` in the S3 key.

If the source download fails with `Access denied to connection` or
`Failed to get access token`, check that the connection is `AVAILABLE` and the app has
access to the repository. If it fails because of the cross-Region connection, do not widen
permissions; report it.

## 10. Verify billing and the budget alert

```bash
aws budgets describe-budgets --account-id "$ACCOUNT_ID" \
  --query 'Budgets[].{name:BudgetName,limit:BudgetLimit,type:BudgetType}'
```

Confirm the USD 5/month cost budget exists and its alert subscribers are correct. A budget
only alerts; it does not stop spending ([COST_CONTROL.md](COST_CONTROL.md)). After the first
build, check **Billing → Bills** and **Cost Explorer** for CodeBuild, CloudWatch and S3
line items. Billing data can lag by up to a day.

## 11. Stop, disable or delete safely

- **Stop a running build:**
  `aws codebuild stop-build --region "$AWS_REGION" --id "$BUILD_ID"`.
- **Nothing runs while idle:** the project has no webhook or schedule, so it only builds when
  started manually.
- **Revoke source access without deleting anything:** in GitHub, under organization settings
  → GitHub Apps → AWS Connector for GitHub, remove the repository. Or delete the
  connection:
  `aws codeconnections delete-connection --region "$CONNECTION_REGION" --connection-arn "$CONNECTION_ARN"`.
- **Delete the stack** (removes the project, role and log group, including logs):
  `aws cloudformation delete-stack --region "$AWS_REGION" --stack-name "$STACK"`, then
  `aws cloudformation wait stack-delete-complete --region "$AWS_REGION" --stack-name "$STACK"`.
- **The bucket is never touched by the stack.** Uploaded manifests under
  `${PREFIX}runs/` expire through the bucket's existing 7-day lifecycle rule. Remove one
  earlier with
  `aws s3api delete-object --bucket "$BUCKET" --expected-bucket-owner "$ACCOUNT_ID" --key <key>`.
