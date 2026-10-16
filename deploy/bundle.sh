#!/usr/bin/env bash
# Package the tracked source, the built web app and the evaluation results, and upload them.
#   AWS_PROFILE=<profile> bash deploy/bundle.sh
set -euo pipefail
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
(cd web && npm run build >/dev/null)
rm -rf var/bundle
STAGE=var/bundle/encore
mkdir -p "$STAGE"
git ls-files --cached --others --exclude-standard | tar -cf - -T - | tar -xf - -C "$STAGE"
mkdir -p "$STAGE/web" "$STAGE/eval"
cp -r web/dist "$STAGE/web/"
if [ -f eval/results.json ]; then cp eval/results.json "$STAGE/eval/"; fi
tar -czf var/bundle/bundle.tgz -C var/bundle encore
aws s3 cp var/bundle/bundle.tgz "s3://encore-deploy-$ACCOUNT/bundle.tgz" --only-show-errors
ls -la var/bundle/bundle.tgz
