# Event-Driven AWS Log Enabler

Automatically creates Glue catalog databases and Athena tables when logging is enabled on ALB, WAF, or CloudFront in any AWS region.

## Architecture Options

### Option 1: Same Region (Simplest)

```
┌─────────────────────────────────────────────────────────────┐
│  ap-southeast-2 (Central = Source)                          │
│                                                             │
│  User enables ALB logging                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │    CloudTrail       │                                   │
│  │  (Event History)    │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │  EventBridge Rule   │                                   │
│  │  (Default Bus)      │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │  Custom Event Bus   │                                   │
│  │  "log-enablement"   │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │  EventBridge Rule   │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │   Lambda Function   │                                   │
│  │  - Create Glue DB   │                                   │
│  │  - Create Athena    │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │   Glue Catalog      │                                   │
│  │   (ap-southeast-2)  │                                   │
│  └─────────────────────┘                                   │
└─────────────────────────────────────────────────────────────┘

Config:
  central_region: ap-southeast-2
  source_regions:
    - ap-southeast-2
```

### Option 2: Multi-Region (Cross-Region Routing)

```
┌─────────────────────────────────────────────────────────────┐
│  us-east-1 (Source Region)                                  │
│                                                             │
│  User enables ALB logging                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │    CloudTrail       │                                   │
│  │  (Event History)    │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │  EventBridge Rule   │                                   │
│  │  "Forward to        │                                   │
│  │   ap-southeast-2"   │                                   │
│  └─────────────────────┘                                   │
│           │                                                 │
│           │ Cross-Region Event                             │
│           │ Routing                                         │
└───────────┼─────────────────────────────────────────────────┘
            │
            ↓
┌─────────────────────────────────────────────────────────────┐
│  ap-southeast-2 (Central Region)                            │
│                                                             │
│  ┌─────────────────────┐                                   │
│  │  Custom Event Bus   │                                   │
│  │  "log-enablement"   │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │  EventBridge Rule   │                                   │
│  └─────────────────────┘                                   │
│           ↓                                                 │
│  ┌─────────────────────┐                                   │
│  │   Lambda Function   │                                   │
│  │  - Extract region   │                                   │
│  │    (us-east-1)      │                                   │
│  │  - Create Glue DB   │                                   │
│  │    in us-east-1     │                                   │
│  └─────────────────────┘                                   │
│           │                                                 │
│           │ Cross-Region                                    │
│           │ Glue API Call                                   │
└───────────┼─────────────────────────────────────────────────┘
            │
            ↓
┌─────────────────────────────────────────────────────────────┐
│  us-east-1 (Source Region)                                  │
│                                                             │
│  ┌─────────────────────┐                                   │
│  │   Glue Catalog      │                                   │
│  │   (us-east-1)       │                                   │
│  └─────────────────────┘                                   │
└─────────────────────────────────────────────────────────────┘

Config:
  central_region: ap-southeast-2
  source_regions:
    - us-east-1
    - eu-west-1
```

### Option 3: Mixed (Central + Multiple Sources)

```
┌─────────────────────────────────────────────────────────────┐
│  ap-southeast-2 (Central = Source)                          │
│                                                             │
│  Local events → EventBridge → Lambda → Glue (local)        │
└─────────────────────────────────────────────────────────────┘
                              ↑
                              │
            ┌─────────────────┼─────────────────┐
            │                 │                 │
┌───────────┴───────┐  ┌──────┴──────┐  ┌──────┴──────┐
│   us-east-1       │  │  eu-west-1  │  │  us-west-2  │
│   (Source)        │  │  (Source)   │  │  (Source)   │
│                   │  │             │  │             │
│  Events forward → │  │  Events →   │  │  Events →   │
└───────────────────┘  └─────────────┘  └─────────────┘

All events processed by Lambda in ap-southeast-2
Glue catalogs created in respective source regions

Config:
  central_region: ap-southeast-2
  source_regions:
    - ap-southeast-2  # Local
    - us-east-1       # Remote
    - eu-west-1       # Remote
    - us-west-2       # Remote
```

### Comparison

| Aspect | Same Region | Multi-Region |
|--------|-------------|--------------|
| **Complexity** | Simple | Moderate |
| **Latency** | Low (~100ms) | Higher (~200-500ms) |
| **Cost** | Lower | Higher (cross-region data transfer) |
| **Use Case** | Single region deployment | Global infrastructure |
| **Event Flow** | Local only | Cross-region routing |
| **Debugging** | Easier | More complex |

### Data Flow

**Same Region:**
```
ALB Logging Enabled
  → CloudTrail (ap-southeast-2)
  → EventBridge (ap-southeast-2)
  → Lambda (ap-southeast-2)
  → Glue Catalog (ap-southeast-2)
```

**Multi-Region:**
```
ALB Logging Enabled (us-east-1)
  → CloudTrail (us-east-1)
  → EventBridge Rule (us-east-1)
  → Cross-Region Forward
  → EventBridge Bus (ap-southeast-2)
  → Lambda (ap-southeast-2)
  → Glue API Call to us-east-1
  → Glue Catalog (us-east-1)
```

## Features

✅ **Multi-Region Support** - Monitor logging enablement in any AWS region
✅ **User-Configurable** - Choose central region and source regions
✅ **Automatic Detection** - No manual triggers needed
✅ **Event-Driven** - Responds immediately when logging is enabled
✅ **Region-Aware** - Creates Glue catalogs in the correct source region

## Prerequisites

- Python 3.6+
- AWS credentials configured
- IAM permissions for Lambda, EventBridge, Glue, and Athena

## Installation

Install dependencies using pip:

```bash
pip install -r requirements.txt
```

Or install manually:
- boto3: `pip install boto3`
- PyYAML: `pip install pyyaml`

## Quick Start

### 1. Configure Regions

Edit `config.yaml`:

```yaml
# Central region where Lambda runs
central_region: ap-southeast-2

# Regions to monitor
source_regions:
  - us-east-1
  - us-west-2
  - ap-southeast-2
  - eu-west-1
```

### 2. Deploy

```bash
python3 deploy.py
```

### 3. Test

Enable logging on any ALB/WAF/CloudFront in a monitored region:

```bash
# Example: Enable ALB logging in us-east-1
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123 \
  --attributes Key=access_logs.s3.enabled,Value=true \
              Key=access_logs.s3.bucket,Value=my-logs-bucket \
  --region us-east-1
```

The Lambda will automatically create Glue catalog in us-east-1!

## Configuration Options

### config.yaml

```yaml
# Central region (where Lambda is deployed)
central_region: ap-southeast-2

# Source regions (where to monitor for logging enablement)
source_regions:
  - us-east-1      # US East (N. Virginia)
  - us-west-2      # US West (Oregon)
  - eu-west-1      # Europe (Ireland)
  - eu-central-1   # Europe (Frankfurt)
  - ap-southeast-1 # Asia Pacific (Singapore)
  - ap-southeast-2 # Asia Pacific (Sydney)
  - ap-northeast-1 # Asia Pacific (Tokyo)

# SNS notifications (optional)
enable_sns_notifications: false
notification_email: your-email@example.com
```

## Supported Services

| Service | API Event | Detection | Log Types |
|---------|-----------|-----------|-----------|
| **ALB** | `ModifyLoadBalancerAttributes` | Detects when any log type is enabled | Access, Connection, Health |
| **WAF** | `PutLoggingConfiguration` | Detects when logging configuration is added | Traffic |
| **CloudFront** | `UpdateDistribution` | Detects when `logging.enabled = true` | Access |

### ALB Log Types

1. **Access Logs** - HTTP request logs
   - Detects: `access_logs.s3.enabled = true`
   - Database: `alb_access_logs_db`
   - Table: `alb_{alb_name}`

2. **Connection Logs** - TLS handshake logs
   - Detects: `connection_logs.s3.enabled = true`
   - Database: `alb_connection_logs_db`
   - Table: `alb_connection_{alb_name}`

3. **Health Check Logs** - Target health probe logs
   - Detects: `health_check_logs.s3.enabled = true`
   - Database: `alb_health_logs_db`
   - Table: `alb_health_{alb_name}`

**Note**: Lambda creates separate Glue tables for each enabled log type.

### CloudFront Logging Limitations

**Supported:**
- ✅ Standard Logs v1 (Legacy) - Direct S3 delivery via `UpdateDistribution` API

**Not Supported:**
- ❌ Standard Logs v2 - CloudWatch vended logs with partitioning
- ❌ Real-Time Logs - Kinesis Data Streams delivery

**Why**: The solution detects `UpdateDistribution` API calls with `logging.enabled = true`, which only applies to Standard Logs v1. Standard Logs v2 and Real-Time Logs use different APIs and delivery mechanisms.

**Workaround**: For Standard Logs v2 or Real-Time Logs, manually create Glue catalogs or use AWS-provided CloudFormation templates.

## How It Works

1. **User enables logging** in any monitored region (e.g., us-east-1)
2. **CloudTrail captures** the API call (ModifyLoadBalancerAttributes, PutLoggingConfiguration, or UpdateDistribution)
3. **EventBridge rule** forwards event:
   - Same region: Default bus → Custom bus
   - Cross-region: Source region → Central region custom bus
4. **Lambda in central region** receives event and:
   - Extracts region, resource ARN, S3 bucket/prefix
   - Detects which log types were enabled (for ALB: access, connection, health)
   - Creates Glue database(s) in **service region**
   - Creates Athena table(s) with proper schema for each log type
5. **Logs are queryable** via Athena in the service region

**Key Point**: Glue catalogs are created in the **service region** (where the ALB/WAF/CloudFront is), not the central region.

## Deployment Details

### Resources Created

**Central Region (e.g., us-east-1):**
- Lambda function: `EventDrivenLogEnabler`
- Custom event bus: `log-enablement-bus`
- EventBridge rule on custom bus: `LogEnablementTrigger` (triggers Lambda)
- EventBridge rule on default bus: `ForwardLoggingEventsToCustomBus` (forwards CloudTrail events)
- IAM role: `EventDrivenLogEnablerRole` (Lambda execution)
- IAM role: `EventBridgeDefaultToCustomBus` (default to custom bus forwarding)

**Each Source Region (if different from central):**
- EventBridge rule: `ForwardLoggingEvents-to-{central_region}`
- IAM role: `EventBridgeCrossRegion-{region}`

**Note**: For same-region setup (central = source), only central region resources are created.

### IAM Permissions

**Lambda Role (`EventDrivenLogEnablerRole`):**
- **CloudWatch Logs**: 
  - `logs:CreateLogGroup`
  - `logs:CreateLogStream`
  - `logs:PutLogEvents`
- **Glue Catalog**:
  - `glue:CreateDatabase`
  - `glue:CreateTable`
  - `glue:GetTable`
  - `glue:GetDatabase`
- **Athena**:
  - `athena:StartQueryExecution`
  - `athena:GetQueryExecution`
- **S3** (for Athena query results):
  - `s3:GetBucketLocation`
  - `s3:GetObject`
  - `s3:ListBucket`
  - `s3:PutObject`
  - Resource: `arn:aws:s3:::*-logs-*` and `arn:aws:s3:::*-logs-*/*`

**EventBridge Role (`EventBridgeCrossRegion-{region}`):**
- `events:PutEvents` (for cross-region event forwarding)

**EventBridge Role (`EventBridgeDefaultToCustomBus`):**
- `events:PutEvents` (for same-region default bus to custom bus forwarding)

## Testing

### Test by Enabling Logging

**Enable ALB access logs:**
```bash
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123 \
  --attributes Key=access_logs.s3.enabled,Value=true \
              Key=access_logs.s3.bucket,Value=my-logs-bucket \
              Key=access_logs.s3.prefix,Value=alb/my-alb \
  --region us-east-1
```

**Enable all 3 ALB log types:**
```bash
aws elbv2 modify-load-balancer-attributes \
  --load-balancer-arn arn:aws:... \
  --attributes \
    Key=access_logs.s3.enabled,Value=true \
    Key=access_logs.s3.bucket,Value=my-logs-bucket \
    Key=access_logs.s3.prefix,Value=alb/my-alb \
    Key=connection_logs.s3.enabled,Value=true \
    Key=health_check_logs.s3.enabled,Value=true \
  --region us-east-1
```

**Expected Timeline:**
- 0s: Enable logging via AWS CLI
- ~3s: CloudTrail captures API call
- ~10s: EventBridge forwards to Lambda
- ~13s: Lambda creates Glue catalog
- ✅ Total: ~13 seconds end-to-end

**What Lambda Creates:**
- For access logs: `alb_access_logs_db.alb_my_alb`
- For connection logs: `alb_connection_logs_db.alb_connection_my_alb`
- For health logs: `alb_health_logs_db.alb_health_my_alb`

## Monitoring

### View Lambda Logs

```bash
aws logs tail /aws/lambda/EventDrivenLogEnabler --region ap-southeast-2 --follow
```

### Check Glue Databases

```bash
# Check databases created
aws glue get-databases --region us-east-1

# Check tables in a database
aws glue get-tables --database-name alb_access_logs_db --region us-east-1
```

### Query Logs in Athena

```sql
-- Query ALB logs
SELECT * FROM alb_access_logs_db.alb_my_alb_name LIMIT 10;

-- Query WAF logs
SELECT * FROM acl_traffic_logs_db.waf_my_waf_name LIMIT 10;

-- Query CloudFront logs
SELECT * FROM cloudfront_access_logs_db.cloudfront_E1234ABCD5678 LIMIT 10;
```

## Limitations

### CloudFront
- **Only Standard Logs v1 supported** (legacy S3 logging)
- Standard Logs v2 (CloudWatch-based) not detected
- Real-Time Logs (Kinesis-based) not detected
- No partitioning support

### ALB
- Detects all 3 log types: access, connection, health ✅
- No partitioning support in Athena tables

### WAF
- Detects all logging configurations ✅
- No partitioning support in Athena tables

### General
- Glue catalogs created in service region (not central region)
- Requires S3 buckets to already exist
- Does not create S3 buckets (only creates Glue catalogs)
- EventBridge pattern is broad - Lambda filters for actual logging enablement

## Troubleshooting

### Lambda not triggered

1. Check EventBridge rule is enabled:
   ```bash
   aws events describe-rule --name LogEnablementTrigger --event-bus-name log-enablement-bus --region ap-southeast-2
   ```

2. Check CloudTrail is capturing events:
   ```bash
   aws cloudtrail lookup-events --lookup-attributes AttributeKey=EventName,AttributeValue=ModifyLoadBalancerAttributes --region us-east-1
   ```

### Events not forwarding from source region

1. Check source region rule exists:
   ```bash
   aws events list-rules --region us-east-1 | grep ForwardLoggingEvents
   ```

2. Check IAM role has PutEvents permission:
   ```bash
   aws iam get-role-policy --role-name EventBridgeCrossRegion-us-east-1 --policy-name PutEventsPolicy
   ```

### Glue table not created

1. Check Lambda logs for errors
2. Verify S3 bucket exists and has correct permissions
3. Ensure Lambda has Glue permissions in the source region

## Cost Considerations

- **Lambda**: Free tier includes 1M requests/month
- **EventBridge**: $1.00 per million events
- **CloudTrail Event History**: Free (90 days)
- **Glue Catalog**: First 1M objects free, then $1 per 100K objects
- **Athena**: $5 per TB scanned

**Typical monthly cost**: < $5 for moderate usage

## Cleanup

```bash
# Delete Lambda function
aws lambda delete-function --function-name EventDrivenLogEnabler --region ap-southeast-2

# Delete event bus
aws events delete-event-bus --name log-enablement-bus --region ap-southeast-2

# Delete rules in each source region
aws events remove-targets --rule ForwardLoggingEvents-to-ap-southeast-2 --ids 1 --region us-east-1
aws events delete-rule --name ForwardLoggingEvents-to-ap-southeast-2 --region us-east-1

# Delete IAM roles
aws iam delete-role-policy --role-name EventDrivenLogEnablerRole --policy-name LogEnablerPermissions
aws iam delete-role --role-name EventDrivenLogEnablerRole
```

## Files

- `lambda_function.py` - Lambda function code
- `config.yaml` - Region configuration
- `deploy.py` - Automated deployment script
- `README.md` - This file
