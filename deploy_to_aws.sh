#!/bin/bash

EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
KEY_FILE="crypto 2.0 key.pem"

echo "========================================="
echo "AWS EC2 Deployment Script"
echo "========================================="

# Step 1: Test SSH connection
echo "Step 1: Testing SSH connection..."
ssh -i "$KEY_FILE" -o StrictHostKeyChecking=no "$EC2_USER@$EC2_HOST" "echo 'SSH connection successful'" || {
    echo "Error: Cannot connect to EC2 instance"
    exit 1
}

# Step 2: Install Docker
echo "Step 2: Installing Docker..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_HOST" << 'INSTALL_DOCKER'
    sudo apt update
    sudo apt install -y docker.io docker-compose git
    sudo usermod -aG docker ubuntu
    sudo systemctl start docker
    sudo systemctl enable docker
    docker --version
    docker-compose --version
INSTALL_DOCKER

# Step 3: Copy project files
echo "Step 3: Copying project files..."
rsync -avz -e "ssh -i \"$KEY_FILE\"" \
    --exclude='node_modules' \
    --exclude='.next' \
    --exclude='.git' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    ./ "$EC2_USER@$EC2_HOST:~/automated-trading-platform/"

# Step 4: Start application
echo "Step 4: Starting application..."
ssh -i "$KEY_FILE" "$EC2_USER@$EC2_HOST" << 'START_APP'
    cd ~/automated-trading-platform
    docker-compose down
    docker-compose up -d --build
    docker-compose ps
START_APP

echo "Deployment Complete!"
echo "Backend: http://$EC2_HOST:8000"
echo "Frontend: http://$EC2_HOST:3000"
