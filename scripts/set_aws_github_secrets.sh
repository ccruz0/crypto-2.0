#!/usr/bin/env bash
# Extract AWS credentials from local AWS config and help set GitHub secrets
# Usage: ./scripts/set_aws_github_secrets.sh

set -e

echo "🔍 Extracting AWS credentials from local configuration..."
echo ""

# Check if AWS CLI is installed
if ! command -v aws &> /dev/null; then
  echo "❌ AWS CLI is not installed"
  echo "   Install it with: brew install awscli"
  exit 1
fi

# Get AWS credentials from local config
AWS_ACCESS_KEY_ID=$(aws configure get aws_access_key_id 2>/dev/null)
AWS_SECRET_ACCESS_KEY=$(aws configure get aws_secret_access_key 2>/dev/null)
AWS_REGION=$(aws configure get region 2>/dev/null || echo "ap-southeast-1")

if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
  echo "❌ AWS credentials not found in local configuration"
  echo "   Run: aws configure"
  exit 1
fi

echo "✅ Found AWS credentials:"
echo "   AWS_ACCESS_KEY_ID: ${AWS_ACCESS_KEY_ID:0:10}...${AWS_ACCESS_KEY_ID: -4}"
echo "   AWS_SECRET_ACCESS_KEY: ${AWS_SECRET_ACCESS_KEY:0:10}...${AWS_SECRET_ACCESS_KEY: -4}"
echo "   AWS_REGION: $AWS_REGION"
echo ""

# Check if gh CLI is available
if command -v gh &> /dev/null; then
  echo "🚀 GitHub CLI found. Setting secrets..."
  echo ""
  
  read -p "Do you want to set AWS_ACCESS_KEY_ID secret? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "$AWS_ACCESS_KEY_ID" | gh secret set AWS_ACCESS_KEY_ID
    echo "✅ AWS_ACCESS_KEY_ID secret set"
  fi
  
  read -p "Do you want to set AWS_SECRET_ACCESS_KEY secret? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "$AWS_SECRET_ACCESS_KEY" | gh secret set AWS_SECRET_ACCESS_KEY
    echo "✅ AWS_SECRET_ACCESS_KEY secret set"
  fi
  
  echo ""
  echo "✅ AWS secrets configured!"
else
  echo "📝 GitHub CLI not found. Please set secrets manually:"
  echo ""
  echo "Option 1: Install GitHub CLI and run this script again"
  echo "   brew install gh"
  echo "   gh auth login"
  echo ""
  echo "Option 2: Set secrets manually in GitHub:"
  echo "   1. Go to: https://github.com/ccruz0/crypto-2.0/settings/secrets/actions"
  echo "   2. Click 'New repository secret'"
  echo "   3. Add AWS_ACCESS_KEY_ID with value: $AWS_ACCESS_KEY_ID"
  echo "   4. Click 'New repository secret' again"
  echo "   5. Add AWS_SECRET_ACCESS_KEY with value: $AWS_SECRET_ACCESS_KEY"
  echo ""
fi
