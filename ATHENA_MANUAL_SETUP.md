# Athena Manual Setup Guide

If you need to manually create or recreate Athena databases and tables (e.g., after dropping a table, or for resources not managed by the script), use the queries below.

## Prerequisites

- Open the [Athena Console](https://console.aws.amazon.com/athena/)
- Set a query result location under **Settings** → `s3://<your-bucket>/athena-results/`

## S3 Bucket Naming

| Service | Bucket Name |
|---|---|
| CloudFront | `cloudfront-logs-{account_id}-us-east-1` |
| ALB | `alb-logs-{account_id}-{region}` |
| NLB | `nlb-logs-{account_id}-{region}` |
| WAF | `aws-waf-logs-{account_id}-{region}` |
| Bedrock | `bedrock-invocation-logs-{account_id}-{region}` |
| VPC Flow Logs | `vpc-flow-logs-{account_id}-{region}` |

---

## Step 1: Create the Database

Run this once per service type. Safe to re-run — it won't overwrite an existing database.

```sql
CREATE DATABASE IF NOT EXISTS vpc_flow_logs_db;
CREATE DATABASE IF NOT EXISTS cloudfront_access_logs_db;
CREATE DATABASE IF NOT EXISTS alb_access_logs_db;
CREATE DATABASE IF NOT EXISTS alb_connection_logs_db;
CREATE DATABASE IF NOT EXISTS alb_health_logs_db;
CREATE DATABASE IF NOT EXISTS nlb_access_logs_db;
CREATE DATABASE IF NOT EXISTS acl_traffic_logs_db;
CREATE DATABASE IF NOT EXISTS bedrock_invocation_logs_db;
```

---

## Step 2: Create Tables

### CloudFront

Database: `cloudfront_access_logs_db`
Table name: `cloudfront_{distribution_id}`

Replace:
- `{distribution_id}` — CloudFront distribution ID in lowercase, e.g., `e1twpqp39i72km`
- `{bucket_name}` — e.g., `cloudfront-logs-476114114317-us-east-1`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS cloudfront_access_logs_db.cloudfront_{distribution_id} (
  `date` DATE, time STRING, location STRING, bytes BIGINT, request_ip STRING,
  method STRING, host STRING, uri STRING, status INT, referrer STRING,
  user_agent STRING, query_string STRING, cookie STRING, result_type STRING,
  request_id STRING, host_header STRING, request_protocol STRING, request_bytes BIGINT,
  time_taken FLOAT, xforwarded_for STRING, ssl_protocol STRING, ssl_cipher STRING,
  response_result_type STRING, http_version STRING, fle_status STRING, fle_encrypted_fields INT
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
LOCATION 's3://{bucket_name}/cloudfront/{distribution_id}/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS cloudfront_access_logs_db.cloudfront_e1twpqp39i72km (
  `date` DATE, time STRING, location STRING, bytes BIGINT, request_ip STRING,
  method STRING, host STRING, uri STRING, status INT, referrer STRING,
  user_agent STRING, query_string STRING, cookie STRING, result_type STRING,
  request_id STRING, host_header STRING, request_protocol STRING, request_bytes BIGINT,
  time_taken FLOAT, xforwarded_for STRING, ssl_protocol STRING, ssl_cipher STRING,
  response_result_type STRING, http_version STRING, fle_status STRING, fle_encrypted_fields INT
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY '\t'
LOCATION 's3://cloudfront-logs-476114114317-us-east-1/cloudfront/E1TWPQP39I72KM/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

---

### ALB Access Logs

Database: `alb_access_logs_db`
Table name: `alb_{alb_name}`

Replace:
- `{alb_name}` — ALB name with hyphens replaced by underscores, e.g., `k8s_dify_difydev_9a5ab6edcf`
- `{bucket_name}` — e.g., `alb-logs-476114114317-us-east-1`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS alb_access_logs_db.alb_{alb_name} (
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
  'input.regex' = '([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*)[:-]([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-.0-9]*) (|[-0-9]*) (-|[-0-9]*) ([-0-9]*) ([-0-9]*) \"([^ ]*) ([^ ]*) (- |[^ ]*)\" \"([^\"]*)\" ([A-Z0-9-]+) ([A-Za-z0-9.-]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^\"]*)\" ([-.0-9]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^ ]*)\" \"([^\s]+?)\" \"([^\s]+)\" \"([^ ]*)\" \"([^ ]*)\"'
)
LOCATION 's3://{bucket_name}/alb/{alb_name}/';
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS alb_access_logs_db.alb_k8s_dify_difydev_9a5ab6edcf (
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
  'input.regex' = '([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*)[:-]([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-.0-9]*) (|[-0-9]*) (-|[-0-9]*) ([-0-9]*) ([-0-9]*) \"([^ ]*) ([^ ]*) (- |[^ ]*)\" \"([^\"]*)\" ([A-Z0-9-]+) ([A-Za-z0-9.-]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^\"]*)\" ([-.0-9]*) ([^ ]*) \"([^\"]*)\" \"([^\"]*)\" \"([^ ]*)\" \"([^\s]+?)\" \"([^\s]+)\" \"([^ ]*)\" \"([^ ]*)\"'
)
LOCATION 's3://alb-logs-476114114317-us-east-1/alb/k8s-dify-difydev-9a5ab6edcf/';
```

---

### ALB Connection Logs

Database: `alb_connection_logs_db`
Table name: `alb_connection_{alb_name}`

Replace:
- `{alb_name}` — ALB name with hyphens replaced by underscores, e.g., `k8s_dify_difydev_9a5ab6edcf`
- `{bucket_name}` — e.g., `alb-logs-476114114317-us-east-1`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS alb_connection_logs_db.alb_connection_{alb_name} (
  timestamp STRING, client_ip STRING, client_port INT, listener_port INT,
  tls_protocol STRING, tls_cipher STRING, tls_handshake_latency DOUBLE,
  leaf_client_cert_subject STRING, leaf_client_cert_validity STRING,
  leaf_client_cert_serial_number STRING, tls_verify_status STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ' '
LOCATION 's3://{bucket_name}/alb/{alb_name}/connection/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS alb_connection_logs_db.alb_connection_k8s_dify_difydev_9a5ab6edcf (
  timestamp STRING, client_ip STRING, client_port INT, listener_port INT,
  tls_protocol STRING, tls_cipher STRING, tls_handshake_latency DOUBLE,
  leaf_client_cert_subject STRING, leaf_client_cert_validity STRING,
  leaf_client_cert_serial_number STRING, tls_verify_status STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ' '
LOCATION 's3://alb-logs-476114114317-us-east-1/alb/k8s-dify-difydev-9a5ab6edcf/connection/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

---

### ALB Health Check Logs

Database: `alb_health_logs_db`
Table name: `alb_health_{alb_name}`

Replace:
- `{alb_name}` — ALB name with hyphens replaced by underscores, e.g., `k8s_dify_difydev_9a5ab6edcf`
- `{bucket_name}` — e.g., `alb-logs-476114114317-us-east-1`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS alb_health_logs_db.alb_health_{alb_name} (
  timestamp STRING, target_address STRING, target_port INT, target_group STRING,
  target_health_status STRING, target_health_reason STRING, target_health_description STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ' '
LOCATION 's3://{bucket_name}/alb/{alb_name}/health/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS alb_health_logs_db.alb_health_k8s_dify_difydev_9a5ab6edcf (
  timestamp STRING, target_address STRING, target_port INT, target_group STRING,
  target_health_status STRING, target_health_reason STRING, target_health_description STRING
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ' '
LOCATION 's3://alb-logs-476114114317-us-east-1/alb/k8s-dify-difydev-9a5ab6edcf/health/'
TBLPROPERTIES ('skip.header.line.count'='2');
```

---

### NLB Access Logs

> **Note:** NLB access logs are only generated for TLS listeners. TCP-only NLBs will not produce any logs.

Database: `nlb_access_logs_db`
Table name: `nlb_{nlb_name}`

Replace:
- `{nlb_name}` — NLB name with hyphens replaced by underscores, e.g., `my_nlb`
- `{bucket_name}` — e.g., `nlb-logs-476114114317-us-east-1`
- `{account_id}` — e.g., `476114114317`
- `{region}` — e.g., `us-east-1`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS nlb_access_logs_db.nlb_{nlb_name} (
  type STRING, version STRING, time STRING, elb STRING, listener_id STRING,
  client_ip STRING, client_port INT, target_ip STRING, target_port INT,
  tcp_connection_time_ms DOUBLE, tls_handshake_time_ms DOUBLE,
  received_bytes BIGINT, sent_bytes BIGINT, incoming_tls_alert INT,
  cert_arn STRING, certificate_serial STRING, tls_cipher_suite STRING,
  tls_protocol_version STRING, tls_named_group STRING, domain_name STRING,
  alpn_fe_protocol STRING, alpn_be_protocol STRING,
  alpn_client_preference_list STRING, tls_connection_creation_time STRING
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
WITH SERDEPROPERTIES (
  'serialization.format' = '1',
  'input.regex' = '([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*):([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-0-9]*) ([-0-9]*) ([-0-9]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ?([^ ]*)?( .*)?'
)
LOCATION 's3://{bucket_name}/AWSLogs/{account_id}/elasticloadbalancing/{region}/';
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS nlb_access_logs_db.nlb_my_nlb (
  type STRING, version STRING, time STRING, elb STRING, listener_id STRING,
  client_ip STRING, client_port INT, target_ip STRING, target_port INT,
  tcp_connection_time_ms DOUBLE, tls_handshake_time_ms DOUBLE,
  received_bytes BIGINT, sent_bytes BIGINT, incoming_tls_alert INT,
  cert_arn STRING, certificate_serial STRING, tls_cipher_suite STRING,
  tls_protocol_version STRING, tls_named_group STRING, domain_name STRING,
  alpn_fe_protocol STRING, alpn_be_protocol STRING,
  alpn_client_preference_list STRING, tls_connection_creation_time STRING
)
ROW FORMAT SERDE 'org.apache.hadoop.hive.serde2.RegexSerDe'
WITH SERDEPROPERTIES (
  'serialization.format' = '1',
  'input.regex' = '([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*):([0-9]*) ([^ ]*):([0-9]*) ([-.0-9]*) ([-.0-9]*) ([-0-9]*) ([-0-9]*) ([-0-9]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ([^ ]*) ?([^ ]*)?( .*)?'
)
LOCATION 's3://nlb-logs-476114114317-us-east-1/AWSLogs/476114114317/elasticloadbalancing/us-east-1/';
```

---

### WAF Logs

Database: `acl_traffic_logs_db`
Table name: `waf_{webacl_name}`

Replace:
- `{webacl_name}` — WebACL name with hyphens replaced by underscores, e.g., `k8s_dify_waf`
- `{bucket_name}` — e.g., `aws-waf-logs-476114114317-us-east-1`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS acl_traffic_logs_db.waf_{webacl_name} (
  timestamp BIGINT, formatversion INT, webaclid STRING, terminatingruleid STRING,
  terminatingruletype STRING, action STRING, httpsourcename STRING, httpsourceid STRING,
  rulegrouplist ARRAY<STRING>, ratebasedrulelist ARRAY<STRING>, nonterminatingmatchingrules ARRAY<STRING>,
  httprequest STRUCT<
    clientip: STRING, country: STRING,
    headers: ARRAY<STRUCT<name: STRING, value: STRING>>,
    uri: STRING, args: STRING, httpversion: STRING, httpmethod: STRING, requestid: STRING
  >
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://{bucket_name}/AWSLogs/';
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS acl_traffic_logs_db.waf_k8s_dify_waf (
  timestamp BIGINT, formatversion INT, webaclid STRING, terminatingruleid STRING,
  terminatingruletype STRING, action STRING, httpsourcename STRING, httpsourceid STRING,
  rulegrouplist ARRAY<STRING>, ratebasedrulelist ARRAY<STRING>, nonterminatingmatchingrules ARRAY<STRING>,
  httprequest STRUCT<
    clientip: STRING, country: STRING,
    headers: ARRAY<STRUCT<name: STRING, value: STRING>>,
    uri: STRING, args: STRING, httpversion: STRING, httpmethod: STRING, requestid: STRING
  >
)
ROW FORMAT SERDE 'org.openx.data.jsonserde.JsonSerDe'
LOCATION 's3://aws-waf-logs-476114114317-us-east-1/AWSLogs/';
```

---

### VPC Flow Logs

Database: `vpc_flow_logs_db`
Table name: `vpc_0c7aef1e305ee6daa`

Replace:
- `{bucket_name}` — e.g., `vpc-flow-logs-476114114317-ap-southeast-2`
- `{account_id}` — e.g., `476114114317`
- `{region}` — e.g., `ap-southeast-2`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS vpc_flow_logs_db.vpc_0c7aef1e305ee6daa (
  version int, account_id string, interface_id string,
  srcaddr string, dstaddr string, srcport int, dstport int,
  protocol bigint, packets bigint, bytes bigint, start bigint, `end` bigint,
  action string, log_status string, vpc_id string, subnet_id string,
  instance_id string, tcp_flags int, type string, pkt_srcaddr string,
  pkt_dstaddr string, az_id string, sublocation_type string, sublocation_id string,
  pkt_src_aws_service string, pkt_dst_aws_service string,
  flow_direction string, traffic_path int
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
  "storage.location.template" = "s3://{bucket_name}/AWSLogs/{account_id}/vpcflowlogs/{region}/${day}"
);
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS vpc_flow_logs_db.vpc_0c7aef1e305ee6daa (
  version int, account_id string, interface_id string,
  srcaddr string, dstaddr string, srcport int, dstport int,
  protocol bigint, packets bigint, bytes bigint, start bigint, `end` bigint,
  action string, log_status string, vpc_id string, subnet_id string,
  instance_id string, tcp_flags int, type string, pkt_srcaddr string,
  pkt_dstaddr string, az_id string, sublocation_type string, sublocation_id string,
  pkt_src_aws_service string, pkt_dst_aws_service string,
  flow_direction string, traffic_path int
)
PARTITIONED BY (day string)
ROW FORMAT DELIMITED
FIELDS TERMINATED BY ' '
LOCATION 's3://vpc-flow-logs-476114114317-ap-southeast-2/AWSLogs/476114114317/vpcflowlogs/ap-southeast-2/'
TBLPROPERTIES (
  "skip.header.line.count" = "1",
  "projection.enabled" = "true",
  "projection.day.type" = "date",
  "projection.day.range" = "2026/01/01,NOW",
  "projection.day.format" = "yyyy/MM/dd",
  "storage.location.template" = "s3://vpc-flow-logs-476114114317-ap-southeast-2/AWSLogs/476114114317/vpcflowlogs/ap-southeast-2/${day}"
);
```

---

### Bedrock Invocation Logs

Database: `bedrock_invocation_logs_db`
Table name: `bedrock_invocation_logs`

Replace:
- `{bucket_name}` — e.g., `bedrock-invocation-logs-476114114317-ap-southeast-2`
- `{account_id}` — e.g., `476114114317`
- `{region}` — e.g., `ap-southeast-2`

```sql
CREATE EXTERNAL TABLE IF NOT EXISTS bedrock_invocation_logs_db.bedrock_invocation_logs (
  schemaType STRING, timestamp TIMESTAMP, region STRING,
  identity STRUCT<arn: STRING>, operation STRING, modelId STRING,
  requestId STRING, schemaVersion STRING,
  output STRUCT<
    outputTokenCount: INT,
    outputBodyJson: STRUCT<
      metrics: STRUCT<latencyMs: INT>,
      usage: STRUCT<inputTokens: INT, outputTokens: INT, totalTokens: INT>,
      output: STRUCT<message: STRUCT<role: STRING, content: ARRAY<STRUCT<text: STRING>>>>
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
  "storage.location.template" = "s3://{bucket_name}/AWSLogs/{account_id}/BedrockModelInvocationLogs/{region}/${datehour}"
);
```

Example:
```sql
CREATE EXTERNAL TABLE IF NOT EXISTS bedrock_invocation_logs_db.bedrock_invocation_logs (
  schemaType STRING, timestamp TIMESTAMP, region STRING,
  identity STRUCT<arn: STRING>, operation STRING, modelId STRING,
  requestId STRING, schemaVersion STRING,
  output STRUCT<
    outputTokenCount: INT,
    outputBodyJson: STRUCT<
      metrics: STRUCT<latencyMs: INT>,
      usage: STRUCT<inputTokens: INT, outputTokens: INT, totalTokens: INT>,
      output: STRUCT<message: STRUCT<role: STRING, content: ARRAY<STRUCT<text: STRING>>>>
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
LOCATION 's3://bedrock-invocation-logs-476114114317-ap-southeast-2/AWSLogs/476114114317/BedrockModelInvocationLogs/ap-southeast-2/'
TBLPROPERTIES (
  "projection.enabled" = "true",
  "projection.datehour.type" = "date",
  "projection.datehour.range" = "2026/01/09/00,NOW",
  "projection.datehour.format" = "yyyy/MM/dd/HH",
  "projection.datehour.interval" = "1",
  "projection.datehour.interval.unit" = "HOURS",
  "storage.location.template" = "s3://bedrock-invocation-logs-476114114317-ap-southeast-2/AWSLogs/476114114317/BedrockModelInvocationLogs/ap-southeast-2/${datehour}"
);
```

---

## Drop and Recreate a Table

```sql
DROP TABLE IF EXISTS vpc_flow_logs_db.vpc_0c7aef1e305ee6daa;
-- Then run the CREATE EXTERNAL TABLE query above
```

Or via AWS CLI:

```bash
aws glue delete-table --database-name vpc_flow_logs_db --name vpc_0c7aef1e305ee6daa --region ap-southeast-2
```
