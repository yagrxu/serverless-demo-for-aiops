#!/usr/bin/env bash
# Manually trigger a trafgen ECS task in the cloudops-demo account.
# Usage: ./scripts/trigger-trafgen.sh [--profile PROFILE] [--region REGION]

set -euo pipefail

PROFILE="${1:-cloudops-demo}"
REGION="${2:-us-east-1}"
CLUSTER="aiops-cat-demo-trafgen"
TASK_FAMILY="aiopscatdemotrafgenTrafgenTaskDef8E875BB7"
STACK_NAME="aiops-cat-demo-trafgen"

echo ">> Finding latest task definition..."
TASK_DEF=$(aws ecs list-task-definitions \
  --family-prefix "$TASK_FAMILY" \
  --sort DESC \
  --query 'taskDefinitionArns[0]' \
  --output text \
  --region "$REGION" \
  --profile "$PROFILE")

if [ "$TASK_DEF" = "None" ] || [ -z "$TASK_DEF" ]; then
  echo "ERROR: No task definition found for family $TASK_FAMILY"
  exit 1
fi
echo "   Task def: $TASK_DEF"

echo ">> Finding private subnets in trafgen VPC..."
SUBNETS=$(aws ec2 describe-subnets \
  --filters \
    "Name=tag:aws-cdk:subnet-name,Values=Private" \
    "Name=tag:aws:cloudformation:stack-name,Values=*trafgen*" \
  --query 'Subnets[*].SubnetId' \
  --output json \
  --region "$REGION" \
  --profile "$PROFILE")

echo "   Subnets: $SUBNETS"

echo ">> Running task..."
TASK_ARN=$(aws ecs run-task \
  --cluster "$CLUSTER" \
  --task-definition "$TASK_DEF" \
  --launch-type FARGATE \
  --network-configuration "{\"awsvpcConfiguration\":{\"subnets\":$SUBNETS,\"assignPublicIp\":\"DISABLED\"}}" \
  --region "$REGION" \
  --profile "$PROFILE" \
  --query 'tasks[0].taskArn' \
  --output text)

echo ">> Task started: $TASK_ARN"
echo ""
echo "View logs:"
echo "  aws logs tail aiops-cat-demo-trafgen-TrafgenTaskDeftrafgenLogGroup5EBA7AFD-98RudGdr8nFm --follow --region $REGION --profile $PROFILE"
