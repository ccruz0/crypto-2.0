#!/bin/bash

# Auto-deploy script for EC2
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
KEY_FILE="crypto 2.0 key.pem"

echo "========================================="
echo "Auto-deploying to EC2"
echo "========================================="

# Step 1: Commit and push changes
echo "Step 1: Committing and pushing to GitHub..."
git add .
git commit -m "Auto-deploy: $(date)" || echo "No changes to commit"
git push origin main

# Step 2: Pull and rebuild on EC2
echo "Step 2: Deploying to EC2..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_HOST" << 'DEPLOY_COMMANDS'
    cd ~/automated-trading-platform
    git pull origin main
    docker-compose down
    docker-compose build --no-cache backend
    docker-compose up -d
    
    # Wait and test
    sleep 20
    curl -s -H 'X-API-Key: demo-key' 'http://localhost:8000/api/account/balance?exchange=CRYPTO_COM' | python3 -m json.tool
DEPLOY_COMMANDS

echo "Deployment complete!"
