# Minimum IAM Policy for FinXCloud

This document describes the minimum AWS IAM permissions required to run FinXCloud.

## Read-Only Scan Policy

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "FinXCloudCostExplorer",
            "Effect": "Allow",
            "Action": [
                "ce:GetCostAndUsage",
                "ce:GetCostForecast",
                "ce:GetReservationCoverage",
                "ce:GetSavingsPlansCoverage"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudEC2ReadOnly",
            "Effect": "Allow",
            "Action": [
                "ec2:DescribeInstances",
                "ec2:DescribeVolumes",
                "ec2:DescribeSnapshots",
                "ec2:DescribeImages",
                "ec2:DescribeAddresses",
                "ec2:DescribeNatGateways",
                "ec2:DescribeRegions"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudRDSReadOnly",
            "Effect": "Allow",
            "Action": [
                "rds:DescribeDBInstances",
                "rds:DescribeDBSnapshots"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudS3ReadOnly",
            "Effect": "Allow",
            "Action": [
                "s3:ListAllMyBuckets",
                "s3:GetBucketLocation",
                "s3:GetBucketVersioning",
                "s3:GetLifecycleConfiguration",
                "s3:GetEncryptionConfiguration"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudLambdaReadOnly",
            "Effect": "Allow",
            "Action": [
                "lambda:ListFunctions",
                "lambda:GetFunction"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudOpenSearchReadOnly",
            "Effect": "Allow",
            "Action": [
                "es:ListDomainNames",
                "es:DescribeDomains",
                "es:DescribeDomain"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudELBReadOnly",
            "Effect": "Allow",
            "Action": [
                "elasticloadbalancing:DescribeLoadBalancers",
                "elasticloadbalancing:DescribeTargetGroups",
                "elasticloadbalancing:DescribeTargetHealth"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudCloudWatchReadOnly",
            "Effect": "Allow",
            "Action": [
                "cloudwatch:GetMetricStatistics",
                "cloudwatch:ListMetrics"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudSTSIdentity",
            "Effect": "Allow",
            "Action": [
                "sts:GetCallerIdentity"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudOrganizations",
            "Effect": "Allow",
            "Action": [
                "organizations:DescribeOrganization",
                "organizations:ListAccounts"
            ],
            "Resource": "*"
        },
        {
            "Sid": "FinXCloudAssumeRole",
            "Effect": "Allow",
            "Action": [
                "sts:AssumeRole"
            ],
            "Resource": "arn:aws:iam::*:role/OrganizationAccountAccessRole",
            "Condition": {
                "StringEquals": {
                    "aws:PrincipalOrgID": "${aws:PrincipalOrgID}"
                }
            }
        }
    ]
}
```

## Notes

- **Cost Explorer** must be enabled in the AWS account (it is not enabled by default). Enable it in the AWS Billing console.
- **Organizations permissions** are only needed if using `--org` flag for multi-account scanning.
- **AssumeRole** permission is only needed for Organizations cross-account scanning. The target role (`OrganizationAccountAccessRole`) is created by default in member accounts created through AWS Organizations.
- **CloudWatch** permissions are optional if using `--skip-utilization` flag.
- **OpenSearch** permissions use the `es:` action prefix (the AWS service is still registered under the Elasticsearch namespace).
- All permissions are **read-only** — FinXCloud never modifies any AWS resources.

## Custom Role Name

If your organization uses a different role name for cross-account access, use the `--org-role` flag:

```bash
finxcloud scan --org --org-role MyCustomReadOnlyRole
```

Update the IAM policy's `sts:AssumeRole` resource ARN accordingly.
