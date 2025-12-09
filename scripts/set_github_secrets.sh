#!/usr/bin/env bash
# Helper script to extract EC2 credentials from .env file and set GitHub secrets
# Usage: ./scripts/set_github_secrets.sh

set -e

echo "🔍 Extracting EC2 credentials from .env files..."
echo ""

# Try to find EC2 credentials in env files
ENV_FILES=(".env.aws" ".env" ".env.local")

EC2_HOST=""
EC2_KEY_PATH=""

# Try to resolve hilovivo-aws SSH alias first
if [ -z "$EC2_HOST" ]; then
  if ssh -G hilovivo-aws 2>/dev/null | grep -q "^hostname"; then
    EC2_HOST=$(ssh -G hilovivo-aws 2>/dev/null | grep "^hostname " | awk '{print $2}')
    echo "   ✅ Resolved hilovivo-aws SSH alias to: $EC2_HOST"
  fi
fi

# Check for EC2_HOST in env files
for env_file in "${ENV_FILES[@]}"; do
  if [ -f "$env_file" ]; then
    echo "📄 Checking $env_file..."
    
    # Extract EC2_HOST
    if grep -q "EC2_HOST" "$env_file"; then
      FOUND_HOST=$(grep "^EC2_HOST=" "$env_file" | cut -d '=' -f2 | tr -d '"' | tr -d "'" | xargs)
      if [ -n "$FOUND_HOST" ]; then
        EC2_HOST="$FOUND_HOST"
        echo "   ✅ Found EC2_HOST: $EC2_HOST"
      fi
    fi
    
    # Extract EC2_KEY_PATH (path to key file)
    if grep -q "EC2_KEY" "$env_file"; then
      EC2_KEY_PATH=$(grep "^EC2_KEY=" "$env_file" | cut -d '=' -f2 | tr -d '"' | tr -d "'" | xargs)
      echo "   ✅ Found EC2_KEY path: $EC2_KEY_PATH"
    fi
  fi
done

# Also check for PEM key file in repo (exclude venv and node_modules)
if [ -z "$EC2_KEY_PATH" ]; then
  # Check for common PEM file names first
  if [ -f "crypto 2.0 key.pem" ]; then
    EC2_KEY_PATH="crypto 2.0 key.pem"
    echo "   ✅ Found PEM file: $EC2_KEY_PATH"
  else
    PEM_FILES=$(find . -maxdepth 2 -name "*.pem" -type f 2>/dev/null | grep -v node_modules | grep -v ".venv" | head -1)
    if [ -n "$PEM_FILES" ]; then
      EC2_KEY_PATH="$PEM_FILES"
      echo "   ✅ Found PEM file: $EC2_KEY_PATH"
    fi
  fi
fi

# Check SSH key from scripts/ssh_key.sh pattern
if [ -z "$EC2_KEY_PATH" ]; then
  if [ -f "$HOME/.ssh/id_rsa" ]; then
    EC2_KEY_PATH="$HOME/.ssh/id_rsa"
    echo "   ✅ Found default SSH key: $EC2_KEY_PATH"
  fi
fi

echo ""
echo "📋 Credentials found:"
echo "   EC2_HOST: ${EC2_HOST:-❌ Not found}"
echo "   EC2_KEY_PATH: ${EC2_KEY_PATH:-❌ Not found}"
echo ""

# Use default EC2_HOST from scripts if not found
if [ -z "$EC2_HOST" ]; then
  EC2_HOST="175.41.189.249"  # Default from resolved hilovivo-aws
  echo "   ⚠️  Using default EC2_HOST: $EC2_HOST"
fi

if [ -z "$EC2_KEY_PATH" ]; then
  echo "❌ Error: Could not find EC2_KEY_PATH"
  echo "   Please ensure a .pem file exists in the repo root (e.g., 'crypto 2.0 key.pem')"
  exit 1
fi

# Read the key content
if [ ! -f "$EC2_KEY_PATH" ]; then
  echo "❌ Key file not found: $EC2_KEY_PATH"
  exit 1
fi

EC2_KEY_CONTENT=$(cat "$EC2_KEY_PATH")

echo "✅ Ready to set GitHub secrets!"
echo ""
echo "📝 To set these as GitHub secrets, run:"
echo ""
echo "   gh secret set EC2_HOST --body \"$EC2_HOST\""
echo "   gh secret set EC2_KEY --body \"$EC2_KEY_CONTENT\""
echo ""
echo "Or manually set them in GitHub:"
echo "   1. Go to: https://github.com/ccruz0/crypto-2.0/settings/secrets/actions"
echo "   2. Click 'New repository secret'"
echo "   3. Add EC2_HOST with value: $EC2_HOST"
echo "   4. Add EC2_KEY with the content of: $EC2_KEY_PATH"
echo ""
echo "🔑 EC2_KEY content (first 50 chars):"
echo "   ${EC2_KEY_CONTENT:0:50}..."
echo ""
