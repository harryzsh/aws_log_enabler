# AWS Log Enabler

Automates enabling logging for CloudFront, ALB, NLB, WAF, Bedrock, and VPC Flow Logs to S3, then configures Athena for querying.

## Prerequisites

- Python 3.6+
- AWS credentials configured (see AWS Authentication below)
- IAM permissions (see Required Permissions below)

## AWS Authentication

The script supports multiple authentication methods:

### Option 1: Environment Variables (Recommended)
Set AWS credentials as environment variables:

```bash
# For permanent credentials
export AWS_ACCESS_KEY_ID= AK
export AWS_SECRET_ACCESS_KEY= SK

# For temporary credentials (optional)
export AWS_SESSION_TOKEN=Session_Token...

# Run the script
python setup_aws_logging.py resources.yaml
```

### Option 2: Direct Code Configuration
Edit the script and set credentials directly in the code:

```python
# In setup_aws_logging.py, modify these lines:
AWS_ACCESS_KEY_ID = "AK"
AWS_SECRET_ACCESS_KEY = "SK"
AWS_SESSION_TOKEN = None  # Optional for temporary credentials
```

**⚠️ Security Note**: Option 2 is not recommended for production environments as it stores credentials in code.

### Option 3: Default AWS Credentials
If no AKSK is provided, the script falls back to standard AWS credential sources:
- AWS credentials file (`~/.aws/credentials`)
- IAM roles (for EC2 instances)
- AWS CLI configuration (`aws configure`)

### Credential Priority
The script checks credentials in this order:
1. Environment variables (`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`)
2. Direct code configuration (if set in script)
3. Default AWS credentials (IAM roles, `~/.aws/credentials`, etc.)

## Required Permissions

The user/role running this script needs the following IAM permissions:

### Core AWS Services
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity"
      ],
      "Resource": "*"
    }
  ]
}
```

### S3 Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:CreateBucket",
    "s3:HeadBucket",
    "s3:PutBucketOwnershipControls",
    "s3:PutBucketAcl",
    "s3:PutBucketPolicy"
  ],
  "Resource": [
    "arn:aws:s3:::cloudfront-logs-*",
    "arn:aws:s3:::alb-logs-*",
    "arn:aws:s3:::aws-waf-logs-*"
  ]
}
```

### CloudFront Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "cloudfront:GetDistribution",
    "cloudfront:UpdateDistribution"
  ],
  "Resource": "*"
}
```

### ALB Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "elasticloadbalancing:DescribeLoadBalancerAttributes",
    "elasticloadbalancing:ModifyLoadBalancerAttributes"
  ],
  "Resource": "*"
}
```

### NLB Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "elasticloadbalancing:DescribeLoadBalancerAttributes",
    "elasticloadbalancing:ModifyLoadBalancerAttributes"
  ],
  "Resource": "*"
}
```

### VPC Flow Logs Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "ec2:CreateFlowLogs",
    "ec2:DescribeFlowLogs",
    "logs:CreateLogDelivery"
  ],
  "Resource": "*"
}
```

### Transit Gateway Flow Logs Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "ec2:CreateFlowLogs",
    "ec2:DescribeFlowLogs",
    "logs:CreateLogDelivery"
  ],
  "Resource": "*"
}
```

### WAF Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "wafv2:GetLoggingConfiguration",
    "wafv2:PutLoggingConfiguration"
  ],
  "Resource": "*"
}
```

### Bedrock Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:GetModelInvocationLoggingConfiguration",
    "bedrock:PutModelInvocationLoggingConfiguration"
  ],
  "Resource": "*"
}
```

### Glue Catalog Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "glue:CreateDatabase",
    "glue:GetDatabase",
    "glue:CreateTable",
    "glue:GetTable"
  ],
  "Resource": [
    "arn:aws:glue:*:*:catalog",
    "arn:aws:glue:*:*:database/*",
    "arn:aws:glue:*:*:table/*/*"
  ]
}
```

### Athena Permissions
```json
{
  "Effect": "Allow",
  "Action": [
    "athena:StartQueryExecution",
    "athena:GetQueryExecution"
  ],
  "Resource": "*"
}
```

### Complete IAM Policy Example

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "sts:GetCallerIdentity",
        "s3:CreateBucket",
        "s3:HeadBucket",
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketAcl",
        "s3:PutBucketPolicy",
        "cloudfront:GetDistribution",
        "cloudfront:UpdateDistribution",
        "elasticloadbalancing:DescribeLoadBalancerAttributes",
        "elasticloadbalancing:ModifyLoadBalancerAttributes",
        "wafv2:GetLoggingConfiguration",
        "wafv2:PutLoggingConfiguration",
        "bedrock:GetModelInvocationLoggingConfiguration",
        "bedrock:PutModelInvocationLoggingConfiguration",
        "glue:CreateDatabase",
        "glue:GetDatabase",
        "glue:CreateTable",
        "glue:GetTable",
        "athena:StartQueryExecution",
        "athena:GetQueryExecution"
      ],
      "Resource": "*"
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:CreateBucket",
        "s3:HeadBucket",
        "s3:PutBucketOwnershipControls",
        "s3:PutBucketAcl",
        "s3:PutBucketPolicy"
      ],
      "Resource": [
        "arn:aws:s3:::cloudfront-logs-*",
        "arn:aws:s3:::alb-logs-*",
        "arn:aws:s3:::aws-waf-logs-*",
        "arn:aws:s3:::bedrock-invocation-logs-*"
      ]
    }
  ]
}
```

**Note**: Some permissions use `"Resource": "*"` because AWS services like CloudFront, ALB, and WAF don't support resource-level permissions for these specific actions.

## Installation

Install dependencies using pip:

```bash
pip install -r requirements.txt
```

Or install manually:
- boto3: `pip install boto3`
- PyYAML: `pip install pyyaml`

## Quick Start

1. Edit `resources.yaml` with your resources
2. Run: `python setup_aws_logging.py resources.yaml`
3. Query logs in Athena console after 5-15 minutes

## Usage

```bash
python setup_aws_logging.py resources.yaml
```

The script processes all resources defined in the YAML configuration file.

## Configuration

### CloudFront

```yaml
cloudfront:
  - distribution_id: E1234ABCD5678
```

**Notes:**
- Region is always `us-east-1` (CloudFront is global)
- Logs appear in 5-15 minutes
- **VPC origins cannot be updated via API** - enable logging manually in console
- Uses legacy logging (no partitioning support)
- For partitioning, use CloudFront Standard Logging v2 via console

### Application Load Balancer (ALB)

```yaml
alb:
  - arn: arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/app/my-alb/abc123
    logs:
      access: true       # HTTP request logs (default: true)
      connection: false  # TLS connection logs (default: false)
      health: false      # Target health check logs (default: false)
```

**Notes:**
- Access logs appear in 5-60 minutes
- Connection logs capture TLS handshake details
- Health check logs generated every 5 minutes
- Partitioning is automatically disabled (not supported)
- AWS creates folder structure: `{prefix}/AWSLogs/{account}/elasticloadbalancing/{region}/...`

### WAF

```yaml
waf:
  - arn: arn:aws:wafv2:us-east-1:123456789012:regional/webacl/my-waf/abc-123
```

**Notes:**
- Region is automatically extracted from the ARN
- Logs appear in 5 minutes
- Stored in JSON format
- Partitioning is automatically disabled (not supported)
- Bucket name must start with `aws-waf-logs-` (enforced by AWS)

### Network Load Balancer (NLB)

```yaml
nlb:
  - arn: arn:aws:elasticloadbalancing:us-east-1:123456789012:loadbalancer/net/my-nlb/abc123
```

**Notes:**
- NLB logs are **TLS-only** - only generated if the NLB has a TLS listener
- TCP-only NLBs will not generate access logs
- Logs appear every 5 minutes
- S3 path: `{bucket}/AWSLogs/{account}/elasticloadbalancing/{region}/yyyy/mm/dd/`

### Bedrock

```yaml
bedrock:
  - region: ap-southeast-2
  - region: us-east-1
```
**Notes:**
- Enables model invocation logging for all Bedrock models in the specified region
- Logs appear within minutes of model invocations
- Stored in JSON format with hourly partitioning
- Captures text, image, video, and embedding model invocations
- Includes input/output tokens, latency metrics, and full request/response data
- S3 bucket created in the same region as Bedrock
- Athena table uses partition projection for efficient querying

### VPC Flow Logs

```yaml
vpc:
  - vpc_id: vpc-0c7aef1e305ee6daa
    region: ap-southeast-2
```

**Notes:**
- Captures **all IP traffic** (ACCEPT + REJECT) to/from all network interfaces in the VPC
- Includes traffic to NLB, ALB, EC2 instances, and all other resources in the VPC
- Logs appear within 10 minutes (600s aggregation interval)
- Athena table uses daily partition projection for efficient querying
- S3 path: `{bucket}/AWSLogs/{account}/vpcflowlogs/{region}/{yyyy}/{MM}/{dd}/`

### Transit Gateway Flow Logs

```yaml
tgw:
  - tgw_id: tgw-xxxxxxxxxxxxxxxxx
    region: ap-southeast-2
```

**Notes:**
- Captures all IP traffic traversing the Transit Gateway
- Multicast traffic and Connect attachments are not supported
- Logs appear within 10 minutes (600s aggregation interval)
- Athena table uses daily partition projection for efficient querying
- S3 path: `{bucket}/AWSLogs/{account}/vpcflowlogs/{region}/{yyyy}/{MM}/{dd}/`

### S3 Access Logs

```yaml
s3:
  - bucket: my-source-bucket
```

**Notes:**
- Region is auto-detected from the source bucket — no need to specify it
- Logs delivered to `s3-access-logs-{account_id}` (shared across all regions)
- Uses Hive-compatible partitioned prefix (`year=YYYY/month=MM/day=DD`) for efficient Athena queries
- Log delivery is best-effort — can be delayed by several hours
- No extra charge for enabling S3 server access logging

## S3 Bucket Naming

Buckets are created with region suffix to support multi-region deployments:
- CloudFront: `cloudfront-logs-{account-id}-us-east-1`
- ALB: `alb-logs-{account-id}-{region}`
- NLB: `nlb-logs-{account-id}-{region}`
- WAF: `aws-waf-logs-{account-id}-{region}`
- Bedrock: `bedrock-invocation-logs-{account-id}-{region}`
- VPC Flow Logs: `vpc-flow-logs-{account-id}-{region}`
- Transit Gateway Flow Logs: `tgw-flow-logs-{account-id}-{region}`
- S3 Access Logs: `s3-access-logs-{account-id}` (shared, no region suffix)

### Multi-Resource Sharing

**Multiple resources in the same region share the same S3 bucket and Athena database:**

Example with 2 ALBs in us-east-1:
- **Shared S3 bucket:** `alb-logs-476114114317-us-east-1`
- **Shared Athena database:** `alb_access_logs_db`
- **Separate tables:**
  - ALB 1: `alb_access_logs_db.alb_my_alb_1`
  - ALB 2: `alb_access_logs_db.alb_my_alb_2`
- **Separate S3 prefixes:**
  - ALB 1 logs: `s3://bucket/alb/my-alb-1/...`
  - ALB 2 logs: `s3://bucket/alb/my-alb-2/...`

This design is efficient - one bucket and database per region, with separate tables and folders per resource.

## Athena Databases

The script creates separate databases for each log type:
- `cloudfront_access_logs_db` - CloudFront access logs
- `alb_access_logs_db` - ALB access logs
- `alb_connection_logs_db` - ALB connection logs
- `alb_health_logs_db` - ALB health check logs
- `nlb_access_logs_db` - NLB TLS access logs
- `acl_traffic_logs_db` - WAF traffic logs
- `bedrock_invocation_logs_db` - Bedrock model invocation logs
- `vpc_flow_logs_db` - VPC Flow Logs
- `tgw_flow_logs_db` - Transit Gateway Flow Logs
- `s3_access_logs_db` - S3 server access logs

## Query Examples

### CloudFront
```sql
SELECT * FROM cloudfront_access_logs_db.cloudfront_{distribution_id} 
WHERE status >= 400 
LIMIT 100;
```

### ALB Access Logs
```sql
SELECT * FROM alb_access_logs_db.alb_{alb_name} 
WHERE elb_status_code = '500' 
ORDER BY time DESC 
LIMIT 100;
```

### ALB Health Check Logs
```sql
SELECT * FROM alb_health_logs_db.alb_health_{alb_name} 
WHERE target_health_status != 'healthy' 
LIMIT 100;
```

### WAF Logs
```sql
SELECT * FROM acl_traffic_logs_db.waf_{webacl_name} 
WHERE action = 'BLOCK' 
LIMIT 100;
```

### NLB Logs
```sql
-- Recent TLS connections
SELECT * FROM nlb_access_logs_db.nlb_{nlb_name}
ORDER BY time DESC
LIMIT 100;

-- TLS protocol version breakdown
SELECT tls_protocol_version, COUNT(*) as connections
FROM nlb_access_logs_db.nlb_{nlb_name}
WHERE tls_protocol_version != '-'
GROUP BY tls_protocol_version
ORDER BY connections DESC;

-- Slowest TLS handshakes
SELECT time, client_ip, tls_handshake_time_ms, tls_protocol_version, tls_cipher_suite
FROM nlb_access_logs_db.nlb_{nlb_name}
ORDER BY tls_handshake_time_ms DESC
LIMIT 10;
```

### VPC Flow Logs
```sql
-- Recent traffic
SELECT * FROM vpc_flow_logs_db.vpc_{vpc_id}
WHERE day >= '2026/01/01'
ORDER BY start DESC
LIMIT 100;

-- Rejected traffic (security analysis)
SELECT srcaddr, dstaddr, dstport, protocol, COUNT(*) as count
FROM vpc_flow_logs_db.vpc_{vpc_id}
WHERE action = 'REJECT'
  AND day >= '2026/01/01'
GROUP BY srcaddr, dstaddr, dstport, protocol
ORDER BY count DESC
LIMIT 20;

-- Traffic to/from specific IPs on NLB port 80
SELECT
  to_iso8601(from_unixtime(start)) as time,
  srcaddr, dstaddr, srcport, dstport, packets, bytes, action
FROM vpc_flow_logs_db.vpc_{vpc_id}
WHERE dstport = 80
  AND (srcaddr = '189.0.1.229' OR dstaddr = '189.0.1.229'
    OR srcaddr = '189.0.1.186' OR dstaddr = '189.0.1.186')
  AND day >= '2026/01/12'
ORDER BY start DESC
LIMIT 100;

-- Top talkers by bytes
SELECT srcaddr, dstaddr, SUM(bytes) as total_bytes
FROM vpc_flow_logs_db.vpc_{vpc_id}
WHERE day >= '2026/01/01'
GROUP BY srcaddr, dstaddr
ORDER BY total_bytes DESC
LIMIT 10;
```
### Bedrock Logs
```sql
-- Query recent invocations with token usage
SELECT 
  timestamp,
  modelId,
  operation,
  input.inputTokenCount as input_tokens,
  output.outputTokenCount as output_tokens,
  output.outputBodyJson.metrics.latencyMs as latency_ms
FROM bedrock_invocation_logs_db.bedrock_invocation_logs
WHERE datehour >= '2026/01/12/00'
ORDER BY timestamp DESC
LIMIT 100;

-- Extract conversation details (system prompt, user input, assistant output)
SELECT
  timestamp,
  input.inputBodyJson.system[1].text as system_prompt,
  input.inputBodyJson.messages[1].content[1].text as user_input,
  output.outputBodyJson.output.message.content[1].text as assistant_output,
  output.outputBodyJson.metrics.latencyMs as latency_ms,
  input.inputTokenCount as input_tokens,
  output.outputTokenCount as output_tokens
FROM bedrock_invocation_logs_db.bedrock_invocation_logs
WHERE datehour >= '2026/01/12/00'
ORDER BY timestamp DESC
LIMIT 100;

-- Find high-latency requests
SELECT 
  timestamp,
  modelId,
  output.outputBodyJson.metrics.latencyMs as latency_ms,
  requestId
FROM bedrock_invocation_logs_db.bedrock_invocation_logs
WHERE datehour >= '2026/01/12/00'
  AND output.outputBodyJson.metrics.latencyMs > 5000
ORDER BY latency_ms DESC;

-- Analyze token usage by model
SELECT 
  modelId,
  COUNT(*) as invocation_count,
  SUM(input.inputTokenCount) as total_input_tokens,
  SUM(output.outputTokenCount) as total_output_tokens,
  AVG(output.outputBodyJson.metrics.latencyMs) as avg_latency_ms
FROM bedrock_invocation_logs_db.bedrock_invocation_logs
WHERE datehour >= '2026/01/12/00'
GROUP BY modelId
ORDER BY invocation_count DESC;
```

### Transit Gateway Flow Logs
```sql
-- Recent traffic through the TGW
SELECT
  to_iso8601(from_unixtime(start)) as time,
  srcaddr, dstaddr, srcport, dstport, protocol,
  packets, bytes, flow_direction,
  tgw_src_vpc_id, tgw_dst_vpc_id
FROM tgw_flow_logs_db.tgw_{tgw_id}
WHERE day >= '2026/01/01'
ORDER BY start DESC
LIMIT 100;

-- Dropped packets analysis
SELECT
  to_iso8601(from_unixtime(start)) as time,
  srcaddr, dstaddr, dstport,
  packets_lost_no_route,
  packets_lost_blackhole,
  packets_lost_mtu_exceeded,
  packets_lost_ttl_expired
FROM tgw_flow_logs_db.tgw_{tgw_id}
WHERE day >= '2026/01/01'
  AND (packets_lost_no_route > 0
    OR packets_lost_blackhole > 0
    OR packets_lost_mtu_exceeded > 0
    OR packets_lost_ttl_expired > 0)
ORDER BY start DESC
LIMIT 100;

-- Top cross-VPC traffic flows
SELECT
  tgw_src_vpc_id, tgw_dst_vpc_id,
  srcaddr, dstaddr,
  SUM(bytes) as total_bytes,
  SUM(packets) as total_packets
FROM tgw_flow_logs_db.tgw_{tgw_id}
WHERE day >= '2026/01/01'
GROUP BY tgw_src_vpc_id, tgw_dst_vpc_id, srcaddr, dstaddr
ORDER BY total_bytes DESC
LIMIT 20;
```

### S3 Access Logs
```sql
-- Recent requests to a bucket
SELECT
  bucket, request_time, remote_ip, requester,
  operation, key, http_status, error_code, bytes_sent
FROM s3_access_logs_db.s3_access_{bucket_name}
WHERE year = '2026' AND month = '04'
ORDER BY request_time DESC
LIMIT 100;

-- Top error codes
SELECT error_code, COUNT(*) as count
FROM s3_access_logs_db.s3_access_{bucket_name}
WHERE year = '2026' AND month = '04'
  AND error_code != '-'
GROUP BY error_code
ORDER BY count DESC;

-- Top requesters by bytes downloaded
SELECT requester, SUM(bytes_sent) as total_bytes
FROM s3_access_logs_db.s3_access_{bucket_name}
WHERE year = '2026' AND month = '04'
GROUP BY requester
ORDER BY total_bytes DESC
LIMIT 20;
```

### Script Behavior
- **Idempotent**: Safe to run multiple times - detects existing resources
- **No deletion**: Script only enables logging, never disables it
- **Table names**: Automatically lowercased by Glue (use lowercase in queries)

### CloudFront Limitations
- **VPC Origins**: Cannot be updated via API - enable logging manually in console
- **Partitioning**: Not supported - script uses legacy logging
  - CloudFront Standard Logging v2 supports partitioning but requires CloudWatch API
  - Legacy logging stores logs flat: `prefix/DIST-ID.2025-12-16-03.xyz.gz`
  - For partitioning, configure Standard Logging v2 manually in console
- **Log delay**: 5-15 minutes after requests
- **File naming**: `<prefix>/<distribution-id>.YYYY-MM-DD-HH.unique-id.gz`

### ALB Limitations
- **Partitioning**: Not supported by this script
- **Folder structure**: AWS controls the path structure under your prefix
- **Log delay**: 5-60 minutes for access logs, 5 minutes for health checks
- **Internal ALBs**: Cannot generate test traffic from outside the VPC

### WAF Limitations
- **Bucket naming**: Must start with `aws-waf-logs-` prefix
- **Partitioning**: Not supported by this script
- **Format**: JSON logs (different from CloudFront/ALB text format)

### Bedrock Limitations
- **Region-wide logging**: Enables logging for all Bedrock models in the region (cannot enable per-model)
- **Log delay**: Logs appear within minutes of model invocations
- **Data types**: Captures text, image, video, and embedding data (all enabled by default)
- **Partition projection**: Uses hourly partitioning with automatic date range projection
- **Query performance**: Partition projection eliminates need for manual partition management

### Transit Gateway Limitations
- **Multicast traffic**: Not supported
- **Connect attachments**: Not supported — Connect flow logs appear under the transport attachment
- **Log delay**: Logs appear within 10 minutes (600s aggregation interval)
- **S3 path**: Shares the `vpcflowlogs` S3 prefix with VPC flow logs (AWS behavior)

### S3 Access Log Limitations
- **Delivery**: Best-effort, logs can be delayed by several hours
- **No partitioning by default**: This script uses Hive-compatible partitioned prefix (`EventTime`) for Athena efficiency
- **Logging loop**: The log target bucket itself is excluded from logging automatically by AWS

### Multi-Region Deployments
- Each region gets its own S3 bucket (e.g., `alb-logs-{account}-us-east-1`, `alb-logs-{account}-ap-southeast-2`)
- Athena tables created in the same region as the resource
- No cross-region data transfer costs
- Multiple resources in the same region share the same bucket and database (see Multi-Resource Sharing above)

### Cost Considerations
- **S3 storage**: Standard S3 pricing applies
- **Athena queries**: $5 per TB scanned
- **Data transfer**: Free within same region
- **Cross-region**: $0.02/GB if querying from different region
- **Bedrock logging**: No additional charge for logging, only S3 storage and Athena query costs

## Troubleshooting

### No logs appearing
- Wait 5-15 minutes for CloudFront, up to 60 minutes for ALB
- For Bedrock, logs appear within minutes after model invocations
- Check S3 bucket for test files (indicates permissions are correct)
- Verify logging is enabled: check resource configuration

### Athena returns 0 rows
- Verify S3 location has trailing slash in table definition
- Check if logs exist in S3: `aws s3 ls s3://{bucket}/{prefix}/`
- Table names are lowercase - use lowercase in queries
- For Bedrock: Ensure datehour partition is within the projection range

### VPC Origin Error
- CloudFront distributions with VPC origins cannot be updated via API
- Enable logging manually in CloudFront console
- Script will create S3 bucket with correct permissions

### Bucket already exists error
- If bucket exists in different region, script will fail
- Delete old bucket or use the existing one
- Bucket names are globally unique across all AWS accounts

## Cleanup

To remove all resources:

```bash
# Disable logging (manual for each resource)
# Delete Glue databases
aws glue delete-database --name cloudfront_access_logs_db --region us-east-1
aws glue delete-database --name alb_access_logs_db --region us-east-1
aws glue delete-database --name alb_connection_logs_db --region us-east-1
aws glue delete-database --name alb_health_logs_db --region us-east-1
aws glue delete-database --name nlb_access_logs_db --region us-east-1
aws glue delete-database --name acl_traffic_logs_db --region us-east-1
aws glue delete-database --name bedrock_invocation_logs_db --region {region}
aws glue delete-database --name vpc_flow_logs_db --region {region}
aws glue delete-database --name tgw_flow_logs_db --region {region}

# Delete S3 buckets
aws s3 rb s3://cloudfront-logs-{account}-us-east-1 --force
aws s3 rb s3://alb-logs-{account}-{region} --force
aws s3 rb s3://nlb-logs-{account}-{region} --force
aws s3 rb s3://aws-waf-logs-{account}-{region} --force
aws s3 rb s3://bedrock-invocation-logs-{account}-{region} --force
aws s3 rb s3://vpc-flow-logs-{account}-{region} --force
aws s3 rb s3://tgw-flow-logs-{account}-{region} --force
```
