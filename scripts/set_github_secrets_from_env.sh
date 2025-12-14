#!/usr/bin/env bash
# Extract EC2 credentials and set GitHub secrets
# This script reads from your local environment and helps set GitHub Actions secrets

set -e

echo "🔍 Extracting EC2 credentials..."
echo ""

# Resolve hilovivo-aws to IP if it's an SSH alias
EC2_HOST_IP=""
if ssh -G hilovivo-aws 2>/dev/null | grep -q "^hostname"; then
  EC2_HOST_IP=$(ssh -G hilovivo-aws 2>/dev/null | grep "^hostname " | awk '{print $2}')
  echo "✅ Resolved hilovivo-aws to: $EC2_HOST_IP"
fi

# Try to find EC2_HOST in env files or use resolved IP
EC2_HOST="${EC2_HOST_IP:-54.254.150.31}"  # Default from sync_to_aws.sh

# Find PEM key file
PEM_FILE=""
if [ -f "crypto 2.0 key.pem" ]; then
  PEM_FILE="crypto 2.0 key.pem"
elif [ -f "$HOME/.ssh/id_rsa" ]; then
  PEM_FILE="$HOME/.ssh/id_rsa"
else
  PEM_FILES=$(find . -maxdepth 2 -name "*.pem" -type f 2>/dev/null | grep -v node_modules | grep -v ".venv" | head -1)
  if [ -n "$PEM_FILES" ]; then
    PEM_FILE="$PEM_FILES"
  fi
fi

if [ -z "$PEM_FILE" ] || [ ! -f "$PEM_FILE" ]; then
  echo "❌ Error: Could not find PEM key file"
  echo "   Please ensure 'crypto 2.0 key.pem' exists in the repo root"
  exit 1
fi

echo "✅ Found PEM key: $PEM_FILE"
echo ""

# Read key content
EC2_KEY_CONTENT=$(cat "$PEM_FILE")

echo "📋 Credentials to set:"
echo "   EC2_HOST: $EC2_HOST"
echo "   EC2_KEY: [Content of $PEM_FILE]"
echo ""

# Check if gh CLI is available
if command -v gh &> /dev/null; then
  echo "🚀 GitHub CLI found. Setting secrets..."
  echo ""
  
  read -p "Do you want to set EC2_HOST secret? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "$EC2_KEY_CONTENT" | gh secret set EC2_KEY --body-file -
    echo "✅ EC2_KEY secret set"
  fi
  
  read -p "Do you want to set EC2_KEY secret? (y/n) " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "$EC2_HOST" | gh secret set EC2_HOST
    echo "✅ EC2_HOST secret set"
  fi
  
  echo ""
  echo "✅ Secrets configured!"
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
  echo "   3. Add EC2_HOST with value: $EC2_HOST"
  echo "   4. Add EC2_KEY with the content below:"
  echo ""
  echo "--- EC2_KEY content (copy this) ---"
  echo "$EC2_KEY_CONTENT"
  echo "--- End of EC2_KEY content ---"
  echo ""
fi


