#!/usr/bin/env python3
"""
AWS Log Enabler - Automates logging setup for CloudFront, ALB, WAF, and Bedrock

This script:
1. Creates S3 buckets with proper permissions for log delivery
2. Enables logging on AWS resources
3. Creates Athena databases and tables for querying logs

Authentication:
- Set AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY environment variables for AKSK
- Or use default AWS credentials from ~/.aws/credentials or IAM roles

Note: CloudFront distributions with VPC origins cannot be updated via API.
      Enable logging manually in the console for those distributions.
"""
import boto3
import sys
import time
import yaml
import os
from pathlib import Path

# AWS Credentials Configuration
# Option 1: Set environment variables AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY
# Option 2: Set credentials directly in code below (not recommended for production)
AWS_ACCESS_KEY_ID = None  # Set your access key here if not using environment variables
AWS_SECRET_ACCESS_KEY = None  # Set your secret key here if not using environment variables
AWS_SESSION_TOKEN = None  # Optional: Set session token for temporary credentials

# Configure boto3 session with AKSK
access_key = os.environ.get('AWS_ACCESS_KEY_ID') or AWS_ACCESS_KEY_ID
secret_key = os.environ.get('AWS_SECRET_ACCESS_KEY') or AWS_SECRET_ACCESS_KEY
session_token = os.environ.get('AWS_SESSION_TOKEN') or AWS_SESSION_TOKEN

if access_key and secret_key:
    boto3.setup_default_session(
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        aws_session_token=session_token
    )

# ANSI color codes
RED = '\033[91m'
GREEN = '\033[92m'
RESET = '\033[0m'

def create_s3_bucket(s3, bucket_name, region, service_type):
    """
    Create S3 bucket for log storage with appropriate permissions.
    
    Note: us-east-1 buckets cannot specify LocationConstraint.
    CloudFront requires ACLs enabled for log delivery.
    """
    # Check if bucket already exists
    try:
        s3.head_bucket(Bucket=bucket_name)
        print(f"Bucket {RED}already{RESET} exists: {bucket_name}")
        bucket_exists = True
    except:
        bucket_exists = False
    
    # Create bucket if it doesn't exist
    if not bucket_exists:
        create_params = {'Bucket': bucket_name}
        if region != 'us-east-1':
            create_params['CreateBucketConfiguration'] = {'LocationConstraint': region}
        s3.create_bucket(**create_params)
        print(f"Created bucket: {bucket_name}")
    
    # Set CloudFront-specific permissions
    if service_type == 'cloudfront':
        s3.put_bucket_ownership_controls(
            Bucket=bucket_name,
            OwnershipControls={'Rules': [{'ObjectOwnership': 'BucketOwnerPreferred'}]}
        )
        s3.put_bucket_acl(Bucket=bucket_name, ACL='log-delivery-write')

def extract_region_from_arn(arn):
    """
    Extract AWS region from ARN.
    ARN format: arn:aws:service:region:account:resource
    """
    try:
        parts = arn.split(':')
        if len(parts) < 6:
            raise ValueError(f"Invalid ARN format: {arn}")
        region = parts[3]
        if not region:
            raise ValueError(f"Region not found in ARN: {arn}")
        return region
    except Exception as e:
        raise ValueError(f"Failed to parse ARN: {e}")

def setup_cloudfront_logging(resource_id, bucket_name, region):
    """
    Enable CloudFront logging to S3.
    
    Important: CloudFront distributions with VPC origins cannot be updated via API.
    The script detects VPC origins by checking for absence of both CustomOriginConfig
    and S3OriginConfig (VpcOriginConfig is not returned by older boto3 versions).
    """
    import copy
    cf = boto3.client('cloudfront')
    
    dist_resp = cf.get_distribution(Id=resource_id)
    config = copy.deepcopy(dist_resp['Distribution']['DistributionConfig'])
    etag = dist_resp['ETag']
    
    # Check if logging is already enabled to the target bucket
    current_logging = config.get('Logging', {})
    target_bucket = f'{bucket_name}.s3.amazonaws.com'
    target_prefix = f'cloudfront/{resource_id}/'
    
    if (current_logging.get('Enabled') and 
        current_logging.get('Bucket') == target_bucket):
        print(f"CloudFront logging {RED}already{RESET} enabled for {resource_id}")
        print(f"S3 location: s3://{target_bucket}/{target_prefix}")
        return target_prefix, resource_id
    
    # Detect VPC origins: they have neither CustomOriginConfig nor S3OriginConfig
    for origin in config.get('Origins', {}).get('Items', []):
        if 'CustomOriginConfig' not in origin and 'S3OriginConfig' not in origin:
            raise Exception("VPC origins cannot be updated via API. Enable logging manually in the console.")
    
    config['Logging'] = {
        'Enabled': True,
        'IncludeCookies': False,
        'Bucket': target_bucket,
        'Prefix': target_prefix
    }
    
    cf.update_distribution(Id=resource_id, DistributionConfig=config, IfMatch=etag)
    print(f"Enabled CloudFront logging for {resource_id}")
    return target_prefix, resource_id

def setup_alb_logging(resource_arn, bucket_name, region, log_config=None):
    """
    Enable ALB logging to S3 (access, connection, and health check logs).
    
    Log types:
    - access: HTTP request logs (default: enabled)
    - connection: TLS connection logs (default: disabled)
    - health: Target health check logs (default: disabled)
    
    Note: AWS automatically creates folder structure under your prefix:
          {prefix}/AWSLogs/{account}/elasticloadbalancing/{region}/{year}/{month}/{day}/
    """
    elb = boto3.client('elbv2', region_name=region)
    s3 = boto3.client('s3', region_name=region)
    
    # Default log configuration
    if log_config is None:
        log_config = {}
    enable_access = log_config.get('access', True)
    enable_connection = log_config.get('connection', False)
    enable_health = log_config.get('health', False)
    
    # Extract ALB name from ARN
    alb_name = resource_arn.split('/')[-2]
    prefix = f'alb/{alb_name}'
    
    # Check if logging is already enabled
    current_attrs = elb.describe_load_balancer_attributes(LoadBalancerArn=resource_arn)
    attrs_dict = {attr['Key']: attr['Value'] for attr in current_attrs['Attributes']}
    
    if (attrs_dict.get('access_logs.s3.enabled') == 'true' and 
        attrs_dict.get('access_logs.s3.bucket') == bucket_name):
        current_prefix = attrs_dict.get('access_logs.s3.prefix', '')
        print(f"ALB logging {RED}already{RESET} enabled for {alb_name}")
        print(f"S3 location: s3://{bucket_name}/{current_prefix}")
        
        # Return log configuration for Athena table creation
        log_status = {
            'access': attrs_dict.get('access_logs.s3.enabled') == 'true',
            'connection': attrs_dict.get('connection_logs.s3.enabled') == 'true',
            'health': attrs_dict.get('health_check_logs.s3.enabled') == 'true'
        }
        return f'{current_prefix}/', alb_name, log_status
    
    # Set bucket policy for ALB
    account_id = boto3.client('sts').get_caller_identity()['Account']
    
    # Use service principal (modern approach - works for all regions)
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "logdelivery.elasticloadbalancing.amazonaws.com"},
            "Action": "s3:PutObject",
            "Resource": f"arn:aws:s3:::{bucket_name}/{prefix}/*"
        }]
    }
    s3.put_bucket_policy(Bucket=bucket_name, Policy=str(policy).replace("'", '"'))
    
    # Build attributes list based on log configuration
    attributes = []
    enabled_logs = []
    
    if enable_access:
        attributes.extend([
            {'Key': 'access_logs.s3.enabled', 'Value': 'true'},
            {'Key': 'access_logs.s3.bucket', 'Value': bucket_name},
            {'Key': 'access_logs.s3.prefix', 'Value': prefix}
        ])
        enabled_logs.append('access')
    
    if enable_connection:
        attributes.extend([
            {'Key': 'connection_logs.s3.enabled', 'Value': 'true'},
            {'Key': 'connection_logs.s3.bucket', 'Value': bucket_name},
            {'Key': 'connection_logs.s3.prefix', 'Value': f'{prefix}/connection'}
        ])
        enabled_logs.append('connection')
    
    if enable_health:
        attributes.extend([
            {'Key': 'health_check_logs.s3.enabled', 'Value': 'true'},
            {'Key': 'health_check_logs.s3.bucket', 'Value': bucket_name},
            {'Key': 'health_check_logs.s3.prefix', 'Value': f'{prefix}/health'}
        ])
        enabled_logs.append('health')
    
    elb.modify_load_balancer_attributes(
        LoadBalancerArn=resource_arn,
        Attributes=attributes
    )
    
    print(f"Enabled ALB logging for {alb_name} ({', '.join(enabled_logs)} logs)")
    print(f"S3 location: s3://{bucket_name}/{prefix}/")
    
    # Return log configuration for Athena table creation
    return f'{prefix}/', alb_name, {'access': enable_access, 'connection': enable_connection, 'health': enable_health}

def setup_nlb_logging(resource_arn, bucket_name, region):
    """
    Enable NLB access logging to S3.
    
    Note: NLB logs are TLS-only - only created if the NLB has a TLS listener.
    S3 path: {bucket}/AWSLogs/{account}/elasticloadbalancing/{region}/yyyy/mm/dd/
    Uses same service principal as ALB: logdelivery.elasticloadbalancing.amazonaws.com
    """
    elb = boto3.client('elbv2', region_name=region)
    s3 = boto3.client('s3', region_name=region)

    # Extract NLB name from ARN
    nlb_name = resource_arn.split('/')[-2]

    # Check if logging is already enabled
    current_attrs = elb.describe_load_balancer_attributes(LoadBalancerArn=resource_arn)
    attrs_dict = {attr['Key']: attr['Value'] for attr in current_attrs['Attributes']}

    if (attrs_dict.get('access_logs.s3.enabled') == 'true' and
        attrs_dict.get('access_logs.s3.bucket') == bucket_name):
        print(f"NLB logging {RED}already{RESET} enabled for {nlb_name}")
        print(f"S3 location: s3://{bucket_name}/AWSLogs/")
        return nlb_name

    # Set bucket policy for NLB (same as ALB)
    account_id = boto3.client('sts').get_caller_identity()['Account']
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "logdelivery.elasticloadbalancing.amazonaws.com"},
            "Action": "s3:PutObject",
            "Resource": f"arn:aws:s3:::{bucket_name}/AWSLogs/{account_id}/*"
        }]
    }
    s3.put_bucket_policy(Bucket=bucket_name, Policy=str(policy).replace("'", '"'))

    elb.modify_load_balancer_attributes(
        LoadBalancerArn=resource_arn,
        Attributes=[
            {'Key': 'access_logs.s3.enabled', 'Value': 'true'},
            {'Key': 'access_logs.s3.bucket', 'Value': bucket_name},
        ]
    )

    print(f"Enabled NLB logging for {nlb_name}")
    print(f"S3 location: s3://{bucket_name}/AWSLogs/")
    return nlb_name

def setup_waf_logging(resource_arn, bucket_name, region):
    """
    Enable WAF logging to S3.
    
    Note: WAF bucket names must start with 'aws-waf-logs-' prefix.
    Logs are stored in JSON format at: {bucket}/AWSLogs/{account}/WAFLogs/{region}/{webacl-name}/
    """
    waf = boto3.client('wafv2', region_name=region)
    
    # Extract WebACL name from ARN
    waf_name = resource_arn.split('/')[-2]
    
    # Check if logging is already enabled
    try:
        current_config = waf.get_logging_configuration(ResourceArn=resource_arn)
        current_dest = current_config['LoggingConfiguration']['LogDestinationConfigs'][0]
        if f'arn:aws:s3:::{bucket_name}' in current_dest:
            print(f"WAF logging {RED}already{RESET} enabled for {waf_name}")
            print(f"S3 location: s3://{bucket_name}/AWSLogs/")
            return '', waf_name
    except waf.exceptions.WAFNonexistentItemException:
        pass
    
    waf.put_logging_configuration(
        LoggingConfiguration={
            'ResourceArn': resource_arn,
            'LogDestinationConfigs': [f'arn:aws:s3:::{bucket_name}']
        }
    )
    print(f"Enabled WAF logging for {resource_arn}")
    print(f"S3 location: s3://{bucket_name}/AWSLogs/")
    return '', waf_name

def setup_vpc_flow_logs(vpc_id, bucket_name, region):
    """
    Enable VPC Flow Logs to S3.
    
    S3 path: {bucket}/AWSLogs/{account}/vpcflowlogs/{region}/{yyyy}/{MM}/{dd}/
    Captures all IP traffic (ACCEPT, REJECT) to/from network interfaces in the VPC.
    """
    ec2 = boto3.client('ec2', region_name=region)
    s3 = boto3.client('s3', region_name=region)
    account_id = boto3.client('sts').get_caller_identity()['Account']

    # Check if flow logs already enabled for this VPC to this bucket
    existing = ec2.describe_flow_logs(
        Filters=[
            {'Name': 'resource-id', 'Values': [vpc_id]},
            {'Name': 'log-destination-type', 'Values': ['s3']}
        ]
    )
    for fl in existing.get('FlowLogs', []):
        if bucket_name in fl.get('LogDestination', ''):
            print(f"VPC Flow Logs {RED}already{RESET} enabled for {vpc_id}")
            print(f"S3 location: s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/")
            return vpc_id

    # Set bucket policy for VPC Flow Logs
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "delivery.logs.amazonaws.com"},
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/AWSLogs/{account_id}/*",
                "Condition": {
                    "StringEquals": {
                        "s3:x-amz-acl": "bucket-owner-full-control",
                        "aws:SourceAccount": account_id
                    }
                }
            },
            {
                "Effect": "Allow",
                "Principal": {"Service": "delivery.logs.amazonaws.com"},
                "Action": "s3:GetBucketAcl",
                "Resource": f"arn:aws:s3:::{bucket_name}",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id}
                }
            }
        ]
    }
    s3.put_bucket_policy(Bucket=bucket_name, Policy=str(policy).replace("'", '"'))

    # Enable VPC Flow Logs
    ec2.create_flow_logs(
        ResourceIds=[vpc_id],
        ResourceType='VPC',
        TrafficType='ALL',
        LogDestinationType='s3',
        LogDestination=f'arn:aws:s3:::{bucket_name}',
        LogFormat='${version} ${account-id} ${interface-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${action} ${log-status} ${vpc-id} ${subnet-id} ${instance-id} ${tcp-flags} ${type} ${pkt-srcaddr} ${pkt-dstaddr} ${az-id} ${sublocation-type} ${sublocation-id} ${pkt-src-aws-service} ${pkt-dst-aws-service} ${flow-direction} ${traffic-path}',
        MaxAggregationInterval=600
    )

    print(f"Enabled VPC Flow Logs for {vpc_id}")
    print(f"S3 location: s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/")
    return vpc_id

def setup_s3_access_logging(source_bucket, log_bucket_name):
    """
    Enable S3 server access logging with Hive-compatible partitioned prefix.

    Uses PartitionedPrefix with EventTime so logs land at:
    {log_bucket}/s3/{source_bucket}/year=YYYY/month=MM/day=DD/

    Grants access via bucket policy (recommended). New buckets default to
    BucketOwnerEnforced which disables ACLs — bucket policy is the correct approach.
    """
    # Detect region from source bucket
    s3_global = boto3.client('s3')
    location = s3_global.get_bucket_location(Bucket=source_bucket)
    region = location['LocationConstraint'] or 'us-east-1'

    s3 = boto3.client('s3', region_name=region)
    account_id = boto3.client('sts').get_caller_identity()['Account']

    # Create target log bucket
    create_s3_bucket(s3, log_bucket_name, region, 's3_logs')

    # Grant logging service principal access via bucket policy (no ACL needed)
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "logging.s3.amazonaws.com"},
            "Action": "s3:PutObject",
            "Resource": f"arn:aws:s3:::{log_bucket_name}/s3/{source_bucket}/*",
            "Condition": {
                "StringEquals": {"aws:SourceAccount": account_id},
                "ArnLike": {"aws:SourceArn": f"arn:aws:s3:::{source_bucket}"}
            }
        }]
    }
    s3.put_bucket_policy(Bucket=log_bucket_name, Policy=str(policy).replace("'", '"'))

    # Check if logging already enabled to this target
    current = s3.get_bucket_logging(Bucket=source_bucket)
    existing = current.get('LoggingEnabled', {})
    if existing.get('TargetBucket') == log_bucket_name:
        print(f"S3 access logging {RED}already{RESET} enabled for {source_bucket}")
        print(f"S3 location: s3://{log_bucket_name}/s3/{source_bucket}/")
        return source_bucket, region

    # Enable logging with Hive-compatible partitioned prefix
    s3.put_bucket_logging(
        Bucket=source_bucket,
        BucketLoggingStatus={
            'LoggingEnabled': {
                'TargetBucket': log_bucket_name,
                'TargetPrefix': f's3/{source_bucket}/',
                'TargetObjectKeyFormat': {
                    'PartitionedPrefix': {
                        'PartitionDateSource': 'EventTime'
                    }
                }
            }
        }
    )

    print(f"Enabled S3 access logging for {source_bucket}")
    print(f"S3 location: s3://{log_bucket_name}/s3/{source_bucket}/")
    return source_bucket, region

    # Check if logging already enabled to this target
    current = s3.get_bucket_logging(Bucket=source_bucket)
    existing = current.get('LoggingEnabled', {})
    if existing.get('TargetBucket') == log_bucket_name:
        print(f"S3 access logging {RED}already{RESET} enabled for {source_bucket}")
        print(f"S3 location: s3://{log_bucket_name}/s3/{source_bucket}/")
        return source_bucket, region

    # Enable logging with Hive-compatible partitioned prefix
    s3.put_bucket_logging(
        Bucket=source_bucket,
        BucketLoggingStatus={
            'LoggingEnabled': {
                'TargetBucket': log_bucket_name,
                'TargetPrefix': f's3/{source_bucket}/',
                'TargetObjectKeyFormat': {
                    'PartitionedPrefix': {
                        'PartitionDateSource': 'EventTime'
                    }
                }
            }
        }
    )

    print(f"Enabled S3 access logging for {source_bucket}")
    print(f"S3 location: s3://{log_bucket_name}/s3/{source_bucket}/")
    return source_bucket, region

def setup_tgw_flow_logs(tgw_id, bucket_name, region):
    """
    Enable Transit Gateway Flow Logs to S3.

    S3 path: {bucket}/AWSLogs/{account}/vpcflowlogs/{region}/{yyyy}/{MM}/{dd}/
    Note: Multicast traffic and Connect attachments are not supported.
    Uses delivery.logs.amazonaws.com service principal (same as VPC flow logs).
    """
    ec2 = boto3.client('ec2', region_name=region)
    s3 = boto3.client('s3', region_name=region)
    account_id = boto3.client('sts').get_caller_identity()['Account']

    # Check if flow logs already enabled for this TGW to this bucket
    existing = ec2.describe_flow_logs(
        Filters=[
            {'Name': 'resource-id', 'Values': [tgw_id]},
            {'Name': 'log-destination-type', 'Values': ['s3']}
        ]
    )
    for fl in existing.get('FlowLogs', []):
        if bucket_name in fl.get('LogDestination', ''):
            print(f"TGW Flow Logs {RED}already{RESET} enabled for {tgw_id}")
            print(f"S3 location: s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/")
            return tgw_id

    # Set bucket policy for TGW Flow Logs
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "delivery.logs.amazonaws.com"},
                "Action": "s3:PutObject",
                "Resource": f"arn:aws:s3:::{bucket_name}/AWSLogs/{account_id}/*",
                "Condition": {
                    "StringEquals": {
                        "s3:x-amz-acl": "bucket-owner-full-control",
                        "aws:SourceAccount": account_id
                    }
                }
            },
            {
                "Effect": "Allow",
                "Principal": {"Service": "delivery.logs.amazonaws.com"},
                "Action": "s3:GetBucketAcl",
                "Resource": f"arn:aws:s3:::{bucket_name}",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id}
                }
            }
        ]
    }
    s3.put_bucket_policy(Bucket=bucket_name, Policy=str(policy).replace("'", '"'))

    # Enable TGW Flow Logs with all version 6 fields
    ec2.create_flow_logs(
        ResourceIds=[tgw_id],
        ResourceType='TransitGateway',
        LogDestinationType='s3',
        LogDestination=f'arn:aws:s3:::{bucket_name}',
        LogFormat='${version} ${resource-type} ${account-id} ${tgw-id} ${tgw-attachment-id} ${tgw-src-vpc-account-id} ${tgw-dst-vpc-account-id} ${tgw-src-vpc-id} ${tgw-dst-vpc-id} ${tgw-src-subnet-id} ${tgw-dst-subnet-id} ${tgw-src-eni} ${tgw-dst-eni} ${tgw-src-az-id} ${tgw-dst-az-id} ${tgw-pair-attachment-id} ${srcaddr} ${dstaddr} ${srcport} ${dstport} ${protocol} ${packets} ${bytes} ${start} ${end} ${log-status} ${type} ${packets-lost-no-route} ${packets-lost-blackhole} ${packets-lost-mtu-exceeded} ${packets-lost-ttl-expired} ${tcp-flags} ${region} ${flow-direction} ${pkt-src-aws-service} ${pkt-dst-aws-service}',
        MaxAggregationInterval=60
    )

    print(f"Enabled TGW Flow Logs for {tgw_id}")
    print(f"S3 location: s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/")
    return tgw_id


def setup_bedrock_logging(region, bucket_name):
    """
    Enable Bedrock model invocation logging to S3.
    
    Note: Bedrock logs are stored at: {bucket}/AWSLogs/{account}/BedrockModelInvocationLogs/{region}/
    Logs are in JSON format with hourly partitioning.
    """
    bedrock = boto3.client('bedrock', region_name=region)
    s3 = boto3.client('s3', region_name=region)
    account_id = boto3.client('sts').get_caller_identity()['Account']
    
    # Check if logging is already enabled
    try:
        current_config = bedrock.get_model_invocation_logging_configuration()
        logging_config = current_config.get('loggingConfig', {})
        
        # Check if S3 logging is enabled to our bucket
        s3_config = logging_config.get('s3Config', {})
        if s3_config.get('bucketName') == bucket_name:
            print(f"Bedrock logging {RED}already{RESET} enabled in {region}")
            print(f"S3 location: s3://{bucket_name}/AWSLogs/{account_id}/BedrockModelInvocationLogs/{region}/")
            return region
    except Exception:
        pass
    
    # Set bucket policy for Bedrock
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "bedrock.amazonaws.com"},
            "Action": "s3:PutObject",
            "Resource": f"arn:aws:s3:::{bucket_name}/AWSLogs/{account_id}/BedrockModelInvocationLogs/*",
            "Condition": {
                "StringEquals": {
                    "aws:SourceAccount": account_id
                },
                "ArnLike": {
                    "aws:SourceArn": f"arn:aws:bedrock:{region}:{account_id}:*"
                }
            }
        }]
    }
    s3.put_bucket_policy(Bucket=bucket_name, Policy=str(policy).replace("'", '"'))
    
    # Enable Bedrock logging
    bedrock.put_model_invocation_logging_configuration(
        loggingConfig={
            's3Config': {
                'bucketName': bucket_name
            },
            'textDataDeliveryEnabled': True,
            'imageDataDeliveryEnabled': True,
            'embeddingDataDeliveryEnabled': True,
            'videoDataDeliveryEnabled': True
        }
    )
    
    print(f"Enabled Bedrock logging in {region}")
    print(f"S3 location: s3://{bucket_name}/AWSLogs/{account_id}/BedrockModelInvocationLogs/{region}/")
    return region

def setup_athena(bucket_name, prefix, service_type, region, resource_name, drop_and_recreate=False):
    """
    Create Athena database and table for querying logs.
    
    Database naming:
    - CloudFront: cloudfront_access_logs_db
    - ALB access: alb_access_logs_db
    - ALB connection: alb_connection_logs_db
    - ALB health: alb_health_logs_db
    - WAF: acl_traffic_logs_db
    - Bedrock: bedrock_logs_db
    
    Note: Partitioning is not supported by this script except for Bedrock.
          Use CloudFront Standard Logging v2 for partition support.
    """
    athena = boto3.client('athena', region_name=region)
    glue = boto3.client('glue', region_name=region)
    account_id = boto3.client('sts').get_caller_identity()['Account']
    
    # Map service types to database names
    db_name_map = {
        'cloudfront': 'cloudfront_access_logs_db',
        'alb': 'alb_access_logs_db',
        'alb_connection': 'alb_connection_logs_db',
        'alb_health': 'alb_health_logs_db',
        'waf': 'acl_traffic_logs_db',
        'bedrock': 'bedrock_invocation_logs_db',
        'nlb': 'nlb_access_logs_db',
        'vpc': 'vpc_flow_logs_db',
        'tgw': 'tgw_flow_logs_db',
        's3_access': 's3_access_logs_db'
    }
    
    db_name = db_name_map.get(service_type, f'{service_type}_logs_db')
    table_name = f'{service_type}_{resource_name.replace("-", "_")}'
    
    # Create database
    try:
        glue.create_database(DatabaseInput={'Name': db_name})
    except glue.exceptions.AlreadyExistsException:
        pass
    
    # Check if table already exists
    try:
        glue.get_table(DatabaseName=db_name, Name=table_name.lower())
        print(f"Athena table {RED}already{RESET} exists: {db_name}.{table_name.lower()}")
        print(f"Query logs with: SELECT * FROM {db_name}.{table_name.lower()} LIMIT 10;")
        return
    except glue.exceptions.EntityNotFoundException:
        pass
    
    # Create table based on service type
    if service_type == 'cloudfront':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          `date` DATE, time STRING, location STRING, bytes BIGINT, request_ip STRING,
          method STRING, host STRING, uri STRING, status INT, referrer STRING,
          user_agent STRING, query_string STRING, cookie STRING, result_type STRING,
          request_id STRING, host_header STRING, request_protocol STRING, request_bytes BIGINT,
          time_taken FLOAT, xforwarded_for STRING, ssl_protocol STRING, ssl_cipher STRING,
          response_result_type STRING, http_version STRING, fle_status STRING, fle_encrypted_fields INT
        ) 
        ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
        LOCATION 's3://{bucket_name}/{prefix}'
        TBLPROPERTIES ('skip.header.line.count'='2');
        """
    elif service_type == 'alb':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          type STRING, time STRING, elb STRING, client_ip STRING, client_port INT,
          target_ip STRING, target_port INT, request_processing_time DOUBLE,
          target_processing_time DOUBLE, response_processing_time DOUBLE,
          elb_status_code STRING, target_status_code STRING, received_bytes BIGINT,
          sent_bytes BIGINT, request_verb STRING, request_url STRING, request_proto STRING,
          user_agent STRING, ssl_cipher STRING, ssl_protocol STRING, target_group_arn STRING,
          trace_id STRING, domain_name STRING, chosen_cert_arn STRING, matched_rule_priority STRING,
          request_creation_time STRING, actions_executed STRING, redirect_url STRING,
          lambda_error_reason STRING, target_port_list STRING, target_status_code_list STRING,
          classification STRING, classification_reason STRING
        ) 
        ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
        WITH SERDEPROPERTIES (
          'serialization.format' = '1',
          'input.regex' = '([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*)[:-]([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-.0-9]*) (|[-0-9]*) (-|[-0-9]*) ([-0-9]*) ([-0-9]*) \"([^ ]*) ([^ ]*) (- |[^ ]*)\" \"([^\"]*)\" ([A-Z0-9-]+) ([A-Za-z0-9.-]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^\"]*)\" ([-.0-9]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^ ]*)\" \"([^\\s]+?)\" \"([^\\s]+)\" \"([^ ]*)\" \"([^ ]*)\"'
        ) LOCATION 's3://{bucket_name}/{prefix}';
        """
    elif service_type == 'alb_connection':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          timestamp STRING, client_ip STRING, client_port INT, listener_port INT,
          tls_protocol STRING, tls_cipher STRING, tls_handshake_latency DOUBLE,
          leaf_client_cert_subject STRING, leaf_client_cert_validity STRING,
          leaf_client_cert_serial_number STRING, tls_verify_status STRING
        ) 
        ROW FORMAT DELIMITED FIELDS TERMINATED BY ' '
        LOCATION 's3://{bucket_name}/{prefix}'
        TBLPROPERTIES ('skip.header.line.count'='2');
        """
    elif service_type == 'alb_health':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          timestamp STRING, target_address STRING, target_port INT, target_group STRING,
          target_health_status STRING, target_health_reason STRING, target_health_description STRING
        ) 
        ROW FORMAT DELIMITED FIELDS TERMINATED BY ' '
        LOCATION 's3://{bucket_name}/{prefix}'
        TBLPROPERTIES ('skip.header.line.count'='2');
        """
    elif service_type == 'nlb':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (          type STRING,
          version STRING,
          time STRING,
          elb STRING,
          listener_id STRING,
          client_ip STRING,
          client_port INT,
          target_ip STRING,
          target_port INT,
          tcp_connection_time_ms DOUBLE,
          tls_handshake_time_ms DOUBLE,
          received_bytes BIGINT,
          sent_bytes BIGINT,
          incoming_tls_alert INT,
          cert_arn STRING,
          certificate_serial STRING,
          tls_cipher_suite STRING,
          tls_protocol_version STRING,
          tls_named_group STRING,
          domain_name STRING,
          alpn_fe_protocol STRING,
          alpn_be_protocol STRING,
          alpn_client_preference_list STRING,
          tls_connection_creation_time STRING
        )
        ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
        WITH SERDEPROPERTIES (
          'serialization.format' = '1',
          'input.regex' = '([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*):([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-0-9]*) ([-0-9]*) ([-0-9]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ?([^ ]*)?( .*)?'
        )
        LOCATION 's3://{bucket_name}/AWSLogs/{account_id}/elasticloadbalancing/{region}/';
        """
    elif service_type == 'vpc':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          version int,
          account_id string,
          interface_id string,
          srcaddr string,
          dstaddr string,
          srcport int,
          dstport int,
          protocol bigint,
          packets bigint,
          bytes bigint,
          start bigint,
          `end` bigint,
          action string,
          log_status string,
          vpc_id string,
          subnet_id string,
          instance_id string,
          tcp_flags int,
          type string,
          pkt_srcaddr string,
          pkt_dstaddr string,
          az_id string,
          sublocation_type string,
          sublocation_id string,
          pkt_src_aws_service string,
          pkt_dst_aws_service string,
          flow_direction string,
          traffic_path int
        )
        PARTITIONED BY (day string)
        ROW FORMAT DELIMITED
        FIELDS TERMINATED BY ' '
        LOCATION 's3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/'
        TBLPROPERTIES (
          "skip.header.line.count" = "1",
          "projection.enabled" = "true",
          "projection.day.type" = "date",
          "projection.day.range" = "2026/01/01,NOW",
          "projection.day.format" = "yyyy/MM/dd",
          "storage.location.template" = "s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/${{day}}"
        );
        """
    elif service_type == 'tgw':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          version int,
          resource_type string,
          account_id string,
          tgw_id string,
          tgw_attachment_id string,
          tgw_src_vpc_account_id string,
          tgw_dst_vpc_account_id string,
          tgw_src_vpc_id string,
          tgw_dst_vpc_id string,
          tgw_src_subnet_id string,
          tgw_dst_subnet_id string,
          tgw_src_eni string,
          tgw_dst_eni string,
          tgw_src_az_id string,
          tgw_dst_az_id string,
          tgw_pair_attachment_id string,
          srcaddr string,
          dstaddr string,
          srcport int,
          dstport int,
          protocol int,
          packets bigint,
          bytes bigint,
          start bigint,
          `end` bigint,
          log_status string,
          type string,
          packets_lost_no_route bigint,
          packets_lost_blackhole bigint,
          packets_lost_mtu_exceeded bigint,
          packets_lost_ttl_expired bigint,
          tcp_flags int,
          region string,
          flow_direction string,
          pkt_src_aws_service string,
          pkt_dst_aws_service string
        )
        PARTITIONED BY (day string)
        ROW FORMAT DELIMITED
        FIELDS TERMINATED BY ' '
        LOCATION 's3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/'
        TBLPROPERTIES (
          "skip.header.line.count" = "1",
          "projection.enabled" = "true",
          "projection.day.type" = "date",
          "projection.day.range" = "2026/01/01,NOW",
          "projection.day.format" = "yyyy/MM/dd",
          "storage.location.template" = "s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/${{day}}"
        );
        """
    elif service_type == 'bedrock':
        create_table = f"""        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          schemaType STRING,
          timestamp TIMESTAMP,
          region STRING,
          identity STRUCT<arn: STRING>,
          operation STRING,
          modelId STRING,
          requestId STRING,
          schemaVersion STRING,
          output STRUCT<
            outputTokenCount: INT,
            outputBodyJson: STRUCT<
              metrics: STRUCT<latencyMs: INT>,
              usage: STRUCT<inputTokens: INT, outputTokens: INT, totalTokens: INT>,
              output: STRUCT<
                message: STRUCT<
                  role: STRING,
                  content: ARRAY<STRUCT<text: STRING>>
                >
              >
            >
          >,
          input STRUCT<
            inputTokenCount: INT,
            inputBodyJson: STRUCT<
              messages: ARRAY<STRUCT<role: STRING, content: ARRAY<STRUCT<text: STRING>>>>,
              system: ARRAY<STRUCT<text: STRING>>,
              inferenceConfig: STRUCT<maxTokens: INT, temperature: DOUBLE, topP: DOUBLE>,
              additionalModelRequestFields: STRUCT<top_k: INT>
            >
          >
        )
        PARTITIONED BY (datehour STRING)
        ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
        WITH SERDEPROPERTIES ('serialization.format' = '1')
        LOCATION 's3://{bucket_name}/AWSLogs/{account_id}/BedrockModelInvocationLogs/{region}/'
        TBLPROPERTIES (
          "projection.enabled" = "true",
          "projection.datehour.type" = "date",
          "projection.datehour.range" = "2026/01/09/00,NOW",
          "projection.datehour.format" = "yyyy/MM/dd/HH",
          "projection.datehour.interval" = "1",
          "projection.datehour.interval.unit" = "HOURS",
          "storage.location.template" = "s3://{bucket_name}/AWSLogs/{account_id}/BedrockModelInvocationLogs/{region}/${{datehour}}"
        );
        """
    elif service_type == 's3_access':
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          bucket_owner string,
          bucket string,
          request_time string,
          remote_ip string,
          requester string,
          request_id string,
          operation string,
          key string,
          request_uri string,
          http_status int,
          error_code string,
          bytes_sent bigint,
          object_size bigint,
          total_time int,
          turn_around_time int,
          referrer string,
          user_agent string,
          version_id string,
          host_id string,
          signature_version string,
          cipher_suite string,
          authentication_type string,
          host_header string,
          tls_version string,
          access_point_arn string,
          acl_required string
        )
        PARTITIONED BY (year string, month string, day string)
        ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
        WITH SERDEPROPERTIES (
          'serialization.format' = '1',
          'input.regex' = '([^ ]*) ([^ ]*) \\[(.*?)\\] ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) (\"[^\"]*\"|-) (-|[0-9]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) (\"[^\"]*\"|-) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*)'
        )
        LOCATION 's3://{bucket_name}/s3/{resource_name}/'
        TBLPROPERTIES (
          "projection.enabled" = "true",
          "projection.year.type" = "integer",
          "projection.year.range" = "2024,2030",
          "projection.month.type" = "integer",
          "projection.month.range" = "1,12",
          "projection.month.digits" = "2",
          "projection.day.type" = "integer",
          "projection.day.range" = "1,31",
          "projection.day.digits" = "2",
          "storage.location.template" = "s3://{bucket_name}/s3/{resource_name}/year=${{year}}/month=${{month}}/day=${{day}}"
        );
        """
    else:  # waf
        create_table = f"""
        CREATE EXTERNAL TABLE IF NOT EXISTS {db_name}.{table_name} (
          timestamp BIGINT, formatversion INT, webaclid STRING, terminatingruleid STRING,
          terminatingruletype STRING, action STRING, httpsourcename STRING, httpsourceid STRING,
          rulegrouplist ARRAY<STRING>, ratebasedrulelist ARRAY<STRING>, nonterminatingmatchingrules ARRAY<STRING>,
          httprequest STRUCT<clientip:STRING, country:STRING, headers:ARRAY<STRUCT<name:STRING,value:STRING>>,
          uri:STRING, args:STRING, httpversion:STRING, httpmethod:STRING, requestid:STRING>
        ) 
        ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
        LOCATION 's3://{bucket_name}/AWSLogs/';
        """
    
    print(f"\nCreate table query:\n{create_table.strip()}\n")

    output_location = f's3://{bucket_name}/athena-results/'
    result = athena.start_query_execution(
        QueryString=create_table,
        QueryExecutionContext={'Database': db_name},
        ResultConfiguration={'OutputLocation': output_location}
    )
    
    time.sleep(2)
    print(f"Created Athena table: {db_name}.{table_name}")
    print(f"Query logs with: SELECT * FROM {db_name}.{table_name} LIMIT 10;")

def process_yaml_config(yaml_file):
    """Process resources from YAML config file"""
    with open(yaml_file, 'r') as f:
        config = yaml.safe_load(f)
    
    account_id = boto3.client('sts').get_caller_identity()['Account']
    results = {'success': [], 'failed': []}
    
    # Validate ARNs before processing
    print("Validating ARNs...")
    for alb in config.get('alb', []):
        try:
            extract_region_from_arn(alb['arn'])
        except ValueError as e:
            print(f"✗ Invalid ALB ARN: {e}")
            results['failed'].append(f"ALB {alb['arn']}: Invalid ARN format")
            return results
    
    for waf in config.get('waf', []):
        try:
            extract_region_from_arn(waf['arn'])
        except ValueError as e:
            print(f"✗ Invalid WAF ARN: {e}")
            results['failed'].append(f"WAF {waf['arn']}: Invalid ARN format")
            return results
    
    print("✓ All ARNs validated\n")
    
    # Process CloudFront distributions
    for cf in config.get('cloudfront', []):
        try:
            dist_id = cf['distribution_id']
            region = 'us-east-1'  # CloudFront is always us-east-1
            
            bucket_name = f'cloudfront-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'cloudfront')
            
            prefix, resource_name = setup_cloudfront_logging(dist_id, bucket_name, region)
            setup_athena(bucket_name, prefix, 'cloudfront', region, resource_name)
            
            results['success'].append(f"CloudFront {dist_id}")
            print(f"✓ CloudFront {dist_id} completed\n")
        except Exception as e:
            results['failed'].append(f"CloudFront {dist_id}: {str(e)}")
            print(f"✗ CloudFront {dist_id} failed: {e}\n")
    
    # Process ALBs
    for alb in config.get('alb', []):
        try:
            arn = alb['arn']
            region = extract_region_from_arn(arn)
            log_config = alb.get('logs', {})
            
            bucket_name = f'alb-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'alb')
            
            prefix, resource_name, log_status = setup_alb_logging(arn, bucket_name, region, log_config)
            
            # Create Athena tables based on YAML config, not current ALB status
            if log_config.get('access', True):
                setup_athena(bucket_name, prefix, 'alb', region, resource_name)
            if log_config.get('connection', False):
                setup_athena(bucket_name, f'{prefix}connection/', 'alb_connection', region, resource_name)
            if log_config.get('health', False):
                setup_athena(bucket_name, f'{prefix}health/', 'alb_health', region, resource_name)
            
            results['success'].append(f"ALB {resource_name}")
            print(f"✓ ALB {resource_name} completed\n")
        except Exception as e:
            results['failed'].append(f"ALB {arn}: {str(e)}")
            print(f"✗ ALB {arn} failed: {e}\n")
    
    # Process NLBs
    for nlb in config.get('nlb', []):
        try:
            arn = nlb['arn']
            region = extract_region_from_arn(arn)

            bucket_name = f'nlb-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'nlb')

            resource_name = setup_nlb_logging(arn, bucket_name, region)
            setup_athena(bucket_name, '', 'nlb', region, resource_name)

            results['success'].append(f"NLB {resource_name}")
            print(f"✓ NLB {resource_name} completed\n")
        except Exception as e:
            results['failed'].append(f"NLB {arn}: {str(e)}")
            print(f"✗ NLB {arn} failed: {e}\n")

    # Process WAF WebACLs
    for waf in config.get('waf', []):
        try:
            arn = waf['arn']
            region = extract_region_from_arn(arn)
            
            bucket_name = f'aws-waf-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'waf')
            
            prefix, resource_name = setup_waf_logging(arn, bucket_name, region)
            setup_athena(bucket_name, prefix, 'waf', region, resource_name)
            
            results['success'].append(f"WAF {resource_name}")
            print(f"✓ WAF {resource_name} completed\n")
        except Exception as e:
            results['failed'].append(f"WAF {arn}: {str(e)}")
            print(f"✗ WAF {arn} failed: {e}\n")
    
    # Process Bedrock regions
    for bedrock_config in config.get('bedrock', []):
        try:
            region = bedrock_config['region']
            
            bucket_name = f'bedrock-invocation-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'bedrock')
            
            resource_name = setup_bedrock_logging(region, bucket_name)
            setup_athena(bucket_name, '', 'bedrock', region, 'invocation_logs')
            
            results['success'].append(f"Bedrock {region}")
            print(f"✓ Bedrock {region} completed\n")
        except Exception as e:
            results['failed'].append(f"Bedrock {region}: {str(e)}")
            print(f"✗ Bedrock {region} failed: {e}\n")

    # Process VPC Flow Logs
    for vpc_config in config.get('vpc', []):
        try:
            vpc_id = vpc_config['vpc_id']
            region = vpc_config['region']

            bucket_name = f'vpc-flow-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'vpc')

            resource_name = setup_vpc_flow_logs(vpc_id, bucket_name, region)
            setup_athena(bucket_name, '', 'vpc', region, vpc_id.replace('-', '_')[4:])

            results['success'].append(f"VPC {vpc_id}")
            print(f"✓ VPC {vpc_id} completed\n")
        except Exception as e:
            results['failed'].append(f"VPC {vpc_id}: {str(e)}")
            print(f"✗ VPC {vpc_id} failed: {e}\n")

    # Process S3 Access Logs
    for s3_config in config.get('s3', []):
        source_bucket = s3_config['bucket']
        try:
            log_bucket_name = f's3-access-logs-{account_id}'
            # detect region inside setup_s3_access_logging
            resource_name, region = setup_s3_access_logging(source_bucket, log_bucket_name)
            setup_athena(log_bucket_name, '', 's3_access', region, source_bucket.replace('-', '_'))

            results['success'].append(f"S3 {source_bucket}")
            print(f"✓ S3 {source_bucket} completed\n")
        except Exception as e:
            results['failed'].append(f"S3 {source_bucket}: {str(e)}")
            print(f"✗ S3 {source_bucket} failed: {e}\n")

    # Process Transit Gateway Flow Logs
    for tgw_config in config.get('tgw', []):
        try:
            tgw_id = tgw_config['tgw_id']
            region = tgw_config['region']

            bucket_name = f'tgw-flow-logs-{account_id}-{region}'
            s3 = boto3.client('s3', region_name=region)
            create_s3_bucket(s3, bucket_name, region, 'tgw')

            resource_name = setup_tgw_flow_logs(tgw_id, bucket_name, region)
            setup_athena(bucket_name, '', 'tgw', region, tgw_id.replace('-', '_')[4:])

            results['success'].append(f"TGW {tgw_id}")
            print(f"✓ TGW {tgw_id} completed\n")
        except Exception as e:
            results['failed'].append(f"TGW {tgw_id}: {str(e)}")
            print(f"✗ TGW {tgw_id} failed: {e}\n")

    return results

if __name__ == '__main__':
    # Check if YAML config file is provided
    if len(sys.argv) == 2 and sys.argv[1].endswith('.yaml'):
        yaml_file = sys.argv[1]
        if not Path(yaml_file).exists():
            print(f"Error: YAML file not found: {yaml_file}")
            sys.exit(1)
        
        print(f"Processing resources from {yaml_file}...\n")
        results = process_yaml_config(yaml_file)
        
        print("\n" + "="*50)
        print("SUMMARY")
        print("="*50)
        print(f"✓ Success: {len(results['success'])}")
        for item in results['success']:
            print(f"  - {item}")
        
        if results['failed']:
            print(f"\n✗ Failed: {len(results['failed'])}")
            for item in results['failed']:
                print(f"  - {item}")
        
        sys.exit(0)
    
    # If we get here, invalid arguments
    print("Usage: python setup_aws_logging.py <config.yaml>")
    print("\nExample: python setup_aws_logging.py resources.yaml")
    sys.exit(1)

