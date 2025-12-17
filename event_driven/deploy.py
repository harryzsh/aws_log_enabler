#!/usr/bin/env python3
"""
Deploy Event-Driven Log Enabler
Supports multi-region deployment with user-configurable regions
"""
import boto3
import yaml
import json
import zipfile
import time
from pathlib import Path

def load_config():
    """Load configuration from config.yaml"""
    with open('config.yaml', 'r') as f:
        return yaml.safe_load(f)

def create_lambda_role(account_id):
    """Create IAM role for Lambda function"""
    iam = boto3.client('iam')
    
    role_name = 'EventDrivenLogEnablerRole'
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "lambda.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    permissions_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "glue:CreateDatabase",
                    "glue:CreateTable",
                    "glue:GetTable",
                    "glue:GetDatabase"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "athena:StartQueryExecution",
                    "athena:GetQueryExecution"
                ],
                "Resource": "*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "s3:GetBucketLocation",
                    "s3:GetObject",
                    "s3:ListBucket",
                    "s3:PutObject"
                ],
                "Resource": [
                    "arn:aws:s3:::*-logs-*",
                    "arn:aws:s3:::*-logs-*/*"
                ]
            }
        ]
    }
    
    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy),
            Description='Role for Event-Driven Log Enabler Lambda'
        )
        print(f"✓ Created IAM role: {role_name}")
    except iam.exceptions.EntityAlreadyExistsException:
        print(f"✓ IAM role already exists: {role_name}")
    
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName='LogEnablerPermissions',
        PolicyDocument=json.dumps(permissions_policy)
    )
    
    return f"arn:aws:iam::{account_id}:role/{role_name}"

def package_lambda():
    """Package Lambda function"""
    print("Packaging Lambda function...")
    
    with zipfile.ZipFile('lambda.zip', 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write('lambda_function.py')
    
    print("✓ Lambda packaged")

def deploy_lambda(central_region, role_arn):
    """Deploy Lambda function to central region"""
    lambda_client = boto3.client('lambda', region_name=central_region)
    function_name = 'EventDrivenLogEnabler'
    
    with open('lambda.zip', 'rb') as f:
        zip_content = f.read()
    
    try:
        lambda_client.create_function(
            FunctionName=function_name,
            Runtime='python3.11',
            Role=role_arn,
            Handler='lambda_function.lambda_handler',
            Code={'ZipFile': zip_content},
            Timeout=300,
            MemorySize=256,
            Description='Event-driven Glue catalog creator for log enablement'
        )
        print(f"✓ Created Lambda function in {central_region}")
    except lambda_client.exceptions.ResourceConflictException:
        lambda_client.update_function_code(
            FunctionName=function_name,
            ZipFile=zip_content
        )
        print(f"✓ Updated Lambda function in {central_region}")
    
    # Wait for Lambda to be active
    time.sleep(5)
    
    response = lambda_client.get_function(FunctionName=function_name)
    return response['Configuration']['FunctionArn']

def create_event_bus(central_region, account_id):
    """Create custom event bus in central region"""
    events = boto3.client('events', region_name=central_region)
    bus_name = 'log-enablement-bus'
    
    try:
        events.create_event_bus(Name=bus_name)
        print(f"✓ Created event bus in {central_region}: {bus_name}")
    except events.exceptions.ResourceAlreadyExistsException:
        print(f"✓ Event bus already exists: {bus_name}")
    
    # Set event bus policy to allow cross-region events
    policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Sid": "AllowCrossRegionEvents",
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account_id}:root"},
            "Action": "events:PutEvents",
            "Resource": f"arn:aws:events:{central_region}:{account_id}:event-bus/{bus_name}"
        }]
    }
    
    events.put_permission(
        EventBusName=bus_name,
        Policy=json.dumps(policy)
    )
    
    return f"arn:aws:events:{central_region}:{account_id}:event-bus/{bus_name}"

def create_central_rule(central_region, lambda_arn, event_bus_arn):
    """Create EventBridge rule in central region to trigger Lambda"""
    events = boto3.client('events', region_name=central_region)
    lambda_client = boto3.client('lambda', region_name=central_region)
    
    rule_name = 'LogEnablementTrigger'
    bus_name = 'log-enablement-bus'
    
    # Rule pattern to match logging enablement events
    event_pattern = {
        "source": ["aws.elasticloadbalancing", "aws.wafv2", "aws.cloudfront"],
        "detail-type": ["AWS API Call via CloudTrail"],
        "detail": {
            "eventName": [
                "ModifyLoadBalancerAttributes",
                "PutLoggingConfiguration",
                "UpdateDistribution"
            ]
        }
    }
    
    # Rule on custom bus to trigger Lambda
    events.put_rule(
        Name=rule_name,
        EventBusName=bus_name,
        EventPattern=json.dumps(event_pattern),
        State='ENABLED',
        Description='Trigger Lambda when logging is enabled'
    )
    
    # Add Lambda as target
    events.put_targets(
        Rule=rule_name,
        EventBusName=bus_name,
        Targets=[{
            'Id': '1',
            'Arn': lambda_arn
        }]
    )
    
    # Grant EventBridge permission to invoke Lambda
    try:
        lambda_client.add_permission(
            FunctionName='EventDrivenLogEnabler',
            StatementId=f'EventBridge-{rule_name}',
            Action='lambda:InvokeFunction',
            Principal='events.amazonaws.com',
            SourceArn=f"arn:aws:events:{central_region}:{boto3.client('sts').get_caller_identity()['Account']}:rule/{bus_name}/{rule_name}"
        )
    except lambda_client.exceptions.ResourceConflictException:
        pass
    
    print(f"✓ Created central rule in {central_region}")
    
    # For same-region setup, create rule on default bus to forward to custom bus
    default_rule_name = 'ForwardLoggingEventsToCustomBus'
    
    # Create IAM role for default bus to put events to custom bus
    iam = boto3.client('iam')
    account_id = boto3.client('sts').get_caller_identity()['Account']
    role_name = 'EventBridgeDefaultToCustomBus'
    
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "events.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName='PutEventsPolicy',
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": "events:PutEvents",
                "Resource": event_bus_arn
            }]
        })
    )
    
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    
    events.put_rule(
        Name=default_rule_name,
        EventPattern=json.dumps(event_pattern),
        State='ENABLED',
        Description='Forward CloudTrail logging events to custom bus'
    )
    
    # Add custom event bus as target with IAM role
    events.put_targets(
        Rule=default_rule_name,
        Targets=[{
            'Id': '1',
            'Arn': event_bus_arn,
            'RoleArn': role_arn
        }]
    )
    
    print(f"✓ Created default bus forwarding rule in {central_region}")

def create_source_region_rule(source_region, central_region, account_id, event_bus_arn):
    """Create EventBridge rule in source region to forward events"""
    events = boto3.client('events', region_name=source_region)
    iam = boto3.client('iam')
    
    rule_name = f'ForwardLoggingEvents-to-{central_region}'
    
    # Create IAM role for EventBridge to put events cross-region
    role_name = f'EventBridgeCrossRegion-{source_region}'
    trust_policy = {
        "Version": "2012-10-17",
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "events.amazonaws.com"},
            "Action": "sts:AssumeRole"
        }]
    }
    
    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust_policy)
        )
    except iam.exceptions.EntityAlreadyExistsException:
        pass
    
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName='PutEventsPolicy',
        PolicyDocument=json.dumps({
            "Version": "2012-10-17",
            "Statement": [{
                "Effect": "Allow",
                "Action": "events:PutEvents",
                "Resource": event_bus_arn
            }]
        })
    )
    
    role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"
    
    # Create rule to match logging events
    event_pattern = {
        "source": ["aws.elasticloadbalancing", "aws.wafv2", "aws.cloudfront"],
        "detail-type": ["AWS API Call via CloudTrail"],
        "detail": {
            "eventName": [
                "ModifyLoadBalancerAttributes",
                "PutLoggingConfiguration",
                "UpdateDistribution"
            ]
        }
    }
    
    events.put_rule(
        Name=rule_name,
        EventPattern=json.dumps(event_pattern),
        State='ENABLED',
        Description=f'Forward logging events to {central_region}'
    )
    
    # Add central event bus as target
    events.put_targets(
        Rule=rule_name,
        Targets=[{
            'Id': '1',
            'Arn': event_bus_arn,
            'RoleArn': role_arn
        }]
    )
    
    print(f"✓ Created forwarding rule in {source_region}")

def main():
    """Main deployment function"""
    print("=" * 60)
    print("Event-Driven Log Enabler Deployment")
    print("=" * 60)
    
    # Load configuration
    config = load_config()
    central_region = config['central_region']
    source_regions = config['source_regions']
    
    print(f"\nCentral Region: {central_region}")
    print(f"Source Regions: {', '.join(source_regions)}")
    print()
    
    # Get account ID
    account_id = boto3.client('sts').get_caller_identity()['Account']
    
    # Step 1: Create IAM role
    print("Step 1: Creating IAM role...")
    role_arn = create_lambda_role(account_id)
    time.sleep(10)  # Wait for IAM propagation
    
    # Step 2: Package Lambda
    print("\nStep 2: Packaging Lambda...")
    package_lambda()
    
    # Step 3: Deploy Lambda to central region
    print(f"\nStep 3: Deploying Lambda to {central_region}...")
    lambda_arn = deploy_lambda(central_region, role_arn)
    
    # Step 4: Create custom event bus in central region
    print(f"\nStep 4: Creating event bus in {central_region}...")
    event_bus_arn = create_event_bus(central_region, account_id)
    
    # Step 5: Create rule in central region
    print(f"\nStep 5: Creating central rule in {central_region}...")
    create_central_rule(central_region, lambda_arn, event_bus_arn)
    
    # Step 6: Create forwarding rules in source regions
    print(f"\nStep 6: Creating forwarding rules in source regions...")
    for region in source_regions:
        if region == central_region:
            print(f"  Skipping {region} (central region)")
            continue
        create_source_region_rule(region, central_region, account_id, event_bus_arn)
    
    print("\n" + "=" * 60)
    print("✅ Deployment Complete!")
    print("=" * 60)
    print(f"\nLambda Function: EventDrivenLogEnabler ({central_region})")
    print(f"Event Bus: log-enablement-bus ({central_region})")
    print(f"Monitoring Regions: {', '.join(source_regions)}")
    print("\nTest by enabling logging on ALB/WAF/CloudFront in any monitored region!")

if __name__ == '__main__':
    main()
