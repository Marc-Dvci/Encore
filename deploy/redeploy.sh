#!/usr/bin/env bash
# Rebuild the bundle and re-run setup_instance.sh on the instance.
#   AWS_PROFILE=<profile> bash deploy/redeploy.sh <instance-id> <host>
set -euo pipefail
export MSYS_NO_PATHCONV=1
IID=${1:?instance id}; HOST=${2:?host}
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
bash deploy/bundle.sh >/dev/null
aws ssm send-command --instance-ids "$IID" --document-name AWS-RunShellScript --query Command.CommandId --output text \
  --parameters "{\"executionTimeout\":[\"1800\"],\"commands\":[\"cd /var/tmp && rm -rf encore && aws s3 cp s3://encore-deploy-$ACCOUNT/bundle.tgz . --only-show-errors && tar -xzf bundle.tgz && rm bundle.tgz && bash encore/deploy/setup_instance.sh $HOST 2>&1 | tail -5\"]}"
