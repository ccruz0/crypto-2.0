#!/bin/bash
# Switch apt sources from HTTP to HTTPS (for instances with egress only on 443).
# Run this ON THE EC2 INSTANCE (e.g. via SSM Session Manager), not on your Mac.
set -e
sudo sed -i.bak 's|http://ap-southeast-1.ec2.archive.ubuntu.com|https://ap-southeast-1.ec2.archive.ubuntu.com|g' /etc/apt/sources.list
sudo sed -i 's|http://security.ubuntu.com|https://security.ubuntu.com|g' /etc/apt/sources.list
sudo sed -i 's|http://archive.ubuntu.com|https://archive.ubuntu.com|g' /etc/apt/sources.list
sudo apt update || true
sudo apt install -y apt-transport-https ca-certificates
sudo apt update
