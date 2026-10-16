#!/usr/bin/env bash
# One-time AWS resources for the Encore demo.
#
#   AWS_PROFILE=<admin profile> bash deploy/provision.sh
#
# Creates a private S3 bucket for deploy bundles, an instance role (SSM, read the bundle bucket,
# read the /encore/* parameters), a security group with 80/443 only (no SSH: administration goes
# through SSM), one t4g.small on Amazon Linux 2023 with IMDSv2 required, and an Elastic IP.
# Stores the two API keys from the local .env as SecureString parameters.
set -euo pipefail
export MSYS_NO_PATHCONV=1

REGION=${AWS_REGION:-us-east-1}
TYPE=${ENCORE_INSTANCE_TYPE:-t4g.small}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
BUCKET=encore-deploy-$ACCOUNT
ROLE=EncoreInstance
A="--region $REGION"

aws s3api head-bucket --bucket "$BUCKET" 2>/dev/null || aws s3api create-bucket --bucket "$BUCKET" $A >/dev/null
aws s3api put-public-access-block --bucket "$BUCKET" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

for k in QLOO_API_KEY GEMINI_API_KEY; do
  v=$(grep -E "^$k=" .env | head -1 | cut -d= -f2- | tr -d '\r')
  if [ -n "$v" ]; then
    aws ssm put-parameter --name "/encore/$k" --type SecureString --value "$v" --overwrite $A >/dev/null
  fi
done

if ! aws iam get-role --role-name $ROLE >/dev/null 2>&1; then
  aws iam create-role --role-name $ROLE --assume-role-policy-document '{
    "Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >/dev/null
  aws iam attach-role-policy --role-name $ROLE --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam create-instance-profile --instance-profile-name $ROLE >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name $ROLE --role-name $ROLE
  sleep 12
fi
aws iam put-role-policy --role-name $ROLE --policy-name EncoreRuntime --policy-document "{
  \"Version\":\"2012-10-17\",\"Statement\":[
   {\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\"],\"Resource\":\"arn:aws:s3:::$BUCKET/*\"},
   {\"Effect\":\"Allow\",\"Action\":[\"ssm:GetParameter\",\"ssm:GetParameters\"],\"Resource\":\"arn:aws:ssm:$REGION:$ACCOUNT:parameter/encore/*\"}]}"

VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text $A)
SUBNET=${ENCORE_SUBNET:-$(aws ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" Name=default-for-az,Values=true \
        --query "Subnets[0].SubnetId" --output text $A)}
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values=encore-web Name=vpc-id,Values="$VPC" \
     --query "SecurityGroups[0].GroupId" --output text $A)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name encore-web --description "Encore: HTTP and HTTPS only" \
       --vpc-id "$VPC" --query GroupId --output text $A)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 80 --cidr 0.0.0.0/0 $A >/dev/null
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 443 --cidr 0.0.0.0/0 $A >/dev/null
fi

AMI=$(aws ssm get-parameter --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64 \
      --query Parameter.Value --output text $A)
IID=$(aws ec2 describe-instances --filters Name=tag:Name,Values=encore Name=instance-state-name,Values=pending,running,stopped \
      --query "Reservations[0].Instances[0].InstanceId" --output text $A)
if [ "$IID" = "None" ]; then
  IID=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --subnet-id "$SUBNET" \
        --security-group-ids "$SG" --iam-instance-profile Name=$ROLE \
        --metadata-options HttpTokens=required,HttpEndpoint=enabled,HttpPutResponseHopLimit=1 \
        --block-device-mappings 'DeviceName=/dev/xvda,Ebs={VolumeSize=12,VolumeType=gp3,Encrypted=true}' \
        --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=encore}]' \
        --query "Instances[0].InstanceId" --output text $A)
  aws ec2 wait instance-running --instance-ids "$IID" $A
fi

EIP=$(aws ec2 describe-addresses --filters Name=tag:Name,Values=encore --query "Addresses[0].PublicIp" --output text $A)
if [ "$EIP" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc --tag-specifications 'ResourceType=elastic-ip,Tags=[{Key=Name,Value=encore}]' \
          --query AllocationId --output text $A)
  aws ec2 associate-address --instance-id "$IID" --allocation-id "$ALLOC" $A >/dev/null
  EIP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query "Addresses[0].PublicIp" --output text $A)
fi

echo "bucket   $BUCKET"
echo "instance $IID ($TYPE)"
echo "host     ${EIP//./-}.sslip.io"
