# AWS Log Enabler

Automates enabling logging for CloudFront, ALB, and WAF to S3, then configures Athena for querying.

## Prerequisites

- Python 3.6+
- boto3: `pip install boto3`
- PyYAML: `pip install pyyaml`
- AWS credentials configured
- IAM permissions for the target service, S3, Glue, and Athena

## Quick Start

1. Edit `resources.yaml` with your resources
2. Run: `python3 setup_aws_logging.py resources.yaml`
3. Query logs in Athena console after 5-15 minutes

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
    region: us-east-1
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
    region: us-east-1
```

**Notes:**
- Logs appear in 5 minutes
- Stored in JSON format
- Partitioning is automatically disabled (not supported)
- Bucket name must start with `aws-waf-logs-` (enforced by AWS)

## S3 Bucket Naming

Buckets are created with region suffix to support multi-region deployments:
- CloudFront: `cloudfront-logs-{account-id}-us-east-1`
- ALB: `alb-logs-{account-id}-{region}`
- WAF: `aws-waf-logs-{account-id}-{region}`

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
- `acl_traffic_logs_db` - WAF traffic logs

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

## Important Notes

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

## Troubleshooting

### No logs appearing
- Wait 5-15 minutes for CloudFront, up to 60 minutes for ALB
- Check S3 bucket for test files (indicates permissions are correct)
- Verify logging is enabled: check resource configuration

### Athena returns 0 rows
- Verify S3 location has trailing slash in table definition
- Check if logs exist in S3: `aws s3 ls s3://{bucket}/{prefix}/`
- Table names are lowercase - use lowercase in queries

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
aws glue delete-database --name acl_traffic_logs_db --region us-east-1

# Delete S3 buckets
aws s3 rb s3://cloudfront-logs-{account}-us-east-1 --force
aws s3 rb s3://alb-logs-{account}-{region} --force
aws s3 rb s3://aws-waf-logs-{account}-{region} --force
```
