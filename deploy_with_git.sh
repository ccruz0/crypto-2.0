#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
KEY_FILE="crypto 2.0 key.pem"

echo "========================================="
echo "Git-based Deployment Script"
echo "========================================="

# Check if remote Git repository is configured
if ! git remote -v | grep -q origin; then
    echo "No Git remote configured."
    echo "Please configure a remote repository first:"
    echo "  git remote add origin <your-repo-url>"
    echo "  git push -u origin main"
    exit 1
fi

# Push latest changes
echo "Step 1: Pushing to Git repository..."
git push origin main

# Deploy to EC2
echo "Step 2: Deploying to EC2..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_HOST" << 'DEPLOY_REMOTE'
    cd ~/automated-trading-platform
    
    # Check if Git is initialized
    if [ ! -d .git ]; then
        echo "Cloning repository..."
        rm -rf ~/automated-trading-platform
        git clone https://github.com/ccruz0/crypto-2.0.git ~/automated-trading-platform
    else
        echo "Pulling latest changes..."
        git pull origin main
    fi
    
    # Rebuild and restart
    echo "Rebuilding Docker containers..."
    docker-compose down
    docker-compose build --no-cache backend
    docker-compose up -d
    
    echo "Deployment complete!"
DEPLOY_REMOTE

echo "Done!"
