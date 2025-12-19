#!/usr/bin/env python3
"""
AWS Log Enabler - Automates logging setup for CloudFront, ALB, and WAF

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

def setup_athena(bucket_name, prefix, service_type, region, resource_name):
    """
    Create Athena database and table for querying logs.
    
    Database naming:
    - CloudFront: cloudfront_access_logs_db
    - ALB access: alb_access_logs_db
    - ALB connection: alb_connection_logs_db
    - ALB health: alb_health_logs_db
    - WAF: acl_traffic_logs_db
    
    Note: Partitioning is not supported by this script.
          Use CloudFront Standard Logging v2 for partition support.
    """
    athena = boto3.client('athena', region_name=region)
    glue = boto3.client('glue', region_name=region)
    
    # Map service types to database names
    db_name_map = {
        'cloudfront': 'cloudfront_access_logs_db',
        'alb': 'alb_access_logs_db',
        'alb_connection': 'alb_connection_logs_db',
        'alb_health': 'alb_health_logs_db',
        'waf': 'acl_traffic_logs_db'
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
    
    output_location = f's3://{bucket_name}/athena-results/'
    result = athena.start_query_execution(
        QueryString=create_table,
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
    
    # Original command-line mode
    if len(sys.argv) < 4 or len(sys.argv) > 5:
        print("Usage:")
        print("  1. YAML config mode: python setup_aws_logging.py <config.yaml>")
        print("  2. Single resource mode: python setup_aws_logging.py <service_type> <resource_id_or_arn> <region> [--partition]")
        print("\nservice_type: cloudfront, alb, or waf")
        print("--partition: Optional flag to enable table partitioning")
        sys.exit(1)
    
    service_type = sys.argv[1].lower()
    resource_id = sys.argv[2]
    region = sys.argv[3]
    enable_partition = '--partition' in sys.argv
    
    account_id = boto3.client('sts').get_caller_identity()['Account']
    bucket_name = f'aws-waf-logs-{account_id}' if service_type == 'waf' else f'{service_type}-logs-{account_id}'
    
    s3 = boto3.client('s3', region_name=region)
    create_s3_bucket(s3, bucket_name, region, service_type)
    
    if service_type == 'cloudfront':
        prefix, resource_name = setup_cloudfront_logging(resource_id, bucket_name, region)
    elif service_type == 'alb':
        prefix, resource_name = setup_alb_logging(resource_id, bucket_name, region)
    elif service_type == 'waf':
        prefix, resource_name = setup_waf_logging(resource_id, bucket_name, region)
    else:
        print(f"Unknown service type: {service_type}")
        sys.exit(1)
    
    setup_athena(bucket_name, prefix, service_type, region, resource_name, enable_partition)
    print(f"\nSetup complete! Logs will be stored in s3://{bucket_name}/{prefix}")
