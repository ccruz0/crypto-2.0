#!/bin/bash

# Script DISABLED - Local Docker usage is now disabled
# All runtime must be on AWS. This script is kept for reference only.

echo "❌ ERROR: Local Docker usage is disabled."
echo "This project now runs exclusively on AWS."
echo ""
echo "Local development workflow:"
echo "1. Edit code locally"
echo "2. Commit and push changes"
echo "3. Pull and run on AWS: ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose up -d'"
exit 1
