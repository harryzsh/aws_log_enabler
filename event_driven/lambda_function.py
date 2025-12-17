"""
Event-Driven AWS Log Enabler - Lambda Function
Triggered by EventBridge when logging is enabled on ALB/WAF/CloudFront
Creates Glue catalog databases and Athena tables in the source region
"""
import boto3
import json
import time

def extract_event_details(event):
    """Extract relevant details from CloudTrail event"""
    detail = event['detail']
    event_name = detail['eventName']
    region = detail['awsRegion']
    account_id = detail['recipientAccountId']
    
    result = {
        'event_name': event_name,
        'region': region,
        'account_id': account_id,
        'service_type': None,
        'resource_arn': None,
        'resource_name': None,
        'bucket_name': None,
        'prefix': None,
        'log_types': []  # For ALB: access, connection, health
    }
    
    # ALB: ModifyLoadBalancerAttributes
    if event_name == 'ModifyLoadBalancerAttributes':
        request_params = detail['requestParameters']
        response_elements = detail['responseElements']
        
        # Check which log types were enabled
        attributes = request_params.get('attributes', [])
        resp_attrs = {attr['key']: attr['value'] for attr in response_elements['attributes']}
        
        log_types_enabled = []
        
        # Check access logs
        if any(attr.get('key') == 'access_logs.s3.enabled' and attr.get('value') == 'true' 
               for attr in attributes):
            log_types_enabled.append('access')
        
        # Check connection logs
        if any(attr.get('key') == 'connection_logs.s3.enabled' and attr.get('value') == 'true' 
               for attr in attributes):
            log_types_enabled.append('connection')
        
        # Check health check logs (probe)
        if any(attr.get('key') == 'health_check_logs.s3.enabled' and attr.get('value') == 'true' 
               for attr in attributes):
            log_types_enabled.append('health')
        
        if log_types_enabled:
            result['service_type'] = 'alb'
            result['resource_arn'] = request_params['loadBalancerArn']
            result['resource_name'] = result['resource_arn'].split('/')[-2]
            result['bucket_name'] = resp_attrs.get('access_logs.s3.bucket')
            result['prefix'] = resp_attrs.get('access_logs.s3.prefix', '')
            result['log_types'] = log_types_enabled  # Track which logs were enabled
    
    # WAF: PutLoggingConfiguration
    elif event_name == 'PutLoggingConfiguration':
        request_params = detail['requestParameters']
        logging_config = request_params.get('loggingConfiguration', {})
        
        result['service_type'] = 'waf'
        result['resource_arn'] = logging_config.get('resourceArn')
        result['resource_name'] = result['resource_arn'].split('/')[-2] if result['resource_arn'] else None
        
        # Extract bucket from log destination
        log_dest = logging_config.get('logDestinationConfigs', [])
        if log_dest:
            bucket_arn = log_dest[0]
            result['bucket_name'] = bucket_arn.split(':::')[-1]
            result['prefix'] = ''
    
    # CloudFront: UpdateDistribution
    elif event_name == 'UpdateDistribution':
        request_params = detail['requestParameters']
        dist_config = request_params.get('distributionConfig', {})
        logging = dist_config.get('logging', {})
        
        if logging.get('enabled'):
            result['service_type'] = 'cloudfront'
            # CloudFront uses 'aRN' not 'arn' in responseElements
            result['resource_arn'] = detail['responseElements'].get('aRN') or detail['responseElements']['distribution'].get('aRN')
            result['resource_name'] = detail['responseElements']['distribution']['id']
            result['bucket_name'] = logging.get('bucket', '').replace('.s3.amazonaws.com', '')
            result['prefix'] = logging.get('prefix', '')
    
    return result

def create_athena_table(bucket_name, prefix, service_type, region, resource_name):
    """Create Athena database and table for querying logs"""
    athena = boto3.client('athena', region_name=region)
    glue = boto3.client('glue', region_name=region)
    
    db_name_map = {
        'cloudfront': 'cloudfront_access_logs_db',
        'alb': 'alb_access_logs_db',
        'alb_connection': 'alb_connection_logs_db',
        'alb_health': 'alb_health_logs_db',
        'waf': 'acl_traffic_logs_db'
    }
    
    db_name = db_name_map.get(service_type)
    table_name = f'{service_type}_{resource_name.replace("-", "_")}'
    
    # Create database if it doesn't exist
    try:
        glue.get_database(Name=db_name)
        print(f"Database already exists: {db_name}")
    except glue.exceptions.EntityNotFoundException:
        glue.create_database(DatabaseInput={'Name': db_name})
        print(f"Created database: {db_name}")
    
    # Check if table exists
    try:
        glue.get_table(DatabaseName=db_name, Name=table_name.lower())
        print(f"Table already exists: {db_name}.{table_name.lower()}")
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
        ) LOCATION 's3://{bucket_name}/{prefix}/';
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
    athena.start_query_execution(
        QueryString=create_table,
        ResultConfiguration={'OutputLocation': output_location}
    )
    
    time.sleep(2)
    print(f"Created Athena table: {db_name}.{table_name}")
    print(f"Query logs: SELECT * FROM {db_name}.{table_name} LIMIT 10;")

def lambda_handler(event, context):
    """
    Lambda handler triggered by EventBridge
    Event contains CloudTrail API call details
    """
    try:
        print(f"Received event: {json.dumps(event)}")
        
        # Extract event details
        details = extract_event_details(event)
        
        if not details['service_type']:
            print("Event does not indicate logging was enabled, skipping")
            return {'statusCode': 200, 'body': 'No action needed'}
        
        print(f"Processing {details['service_type']} logging enablement:")
        print(f"  Region: {details['region']}")
        print(f"  Resource: {details['resource_name']}")
        print(f"  Bucket: {details['bucket_name']}")
        print(f"  Prefix: {details['prefix']}")
        
        # Create Athena tables in service region (same as where resource is)
        if details['service_type'] == 'alb':
            print(f"  Log Types: {', '.join(details['log_types'])}")
            
            for log_type in details['log_types']:
                if log_type == 'access':
                    create_athena_table(
                        bucket_name=details['bucket_name'],
                        prefix=details['prefix'] + '/',
                        service_type='alb',
                        region=details['region'],
                        resource_name=details['resource_name']
                    )
                elif log_type == 'connection':
                    create_athena_table(
                        bucket_name=details['bucket_name'],
                        prefix=details['prefix'] + '/connection/',
                        service_type='alb_connection',
                        region=details['region'],
                        resource_name=details['resource_name']
                    )
                elif log_type == 'health':
                    create_athena_table(
                        bucket_name=details['bucket_name'],
                        prefix=details['prefix'] + '/health/',
                        service_type='alb_health',
                        region=details['region'],
                        resource_name=details['resource_name']
                    )
        else:
            # WAF and CloudFront - single table
            create_athena_table(
                bucket_name=details['bucket_name'],
                prefix=details['prefix'],
                service_type=details['service_type'],
                region=details['region'],
                resource_name=details['resource_name']
            )
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'Glue catalog created successfully',
                'service': details['service_type'],
                'region': details['region'],
                'resource': details['resource_name']
            })
        }
        
    except Exception as e:
        print(f"Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
