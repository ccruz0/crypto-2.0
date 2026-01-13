# Quick SSH Setup for AWS Deployment

## Current Issue
❌ SSH connections timing out to AWS instances

## IP Addresses Found in Codebase
- `54.254.150.31` (primary in scripts)
- `175.41.189.249` (alternative in scripts)  
- `47.130.143.159` (mentioned in docs - might be current Elastic IP)

## Quick Setup Steps

### 1. Check AWS Console
```bash
# Go to AWS Console → EC2 → Instances
# Find your instance and note:
# - Current Public IP
# - Security Group name
# - Instance status (should be "running")
```

### 2. Update Security Group
1. AWS Console → EC2 → Security Groups
2. Select your instance's security group
3. Edit Inbound Rules
4. Add/Edit SSH rule:
   - Type: SSH
   - Port: 22
   - Source: `0.0.0.0/0` (for testing) OR your IP address
   - Save rules

### 3. Verify SSH Key
```bash
# Check key exists and has correct permissions
ls -la ~/.ssh/id_rsa
chmod 600 ~/.ssh/id_rsa
```

### 4. Test Connection
```bash
# Try with the IP from AWS Console
ssh -i ~/.ssh/id_rsa ubuntu@YOUR_INSTANCE_IP

# Or use test script (update IP in script first if needed)
./test_aws_ssh.sh
```

### 5. Update Deployment Script (if IP changed)
Edit `deploy_decision_tracing_fix.sh` and update:
- `EC2_HOST_PRIMARY` with actual IP from AWS Console
- `EC2_HOST_ALTERNATIVE` (if you have multiple instances)

### 6. Deploy
Once SSH works:
```bash
./deploy_decision_tracing_fix.sh
```

## Alternative: Use AWS Session Manager
If you can't configure SSH:
```bash
# Connect via Session Manager (interactive only)
aws ssm start-session --target i-08726dc37133b2454

# Then manually deploy files (see DEPLOYMENT_SUMMARY.md)
```

## Need Help?
See `SSH_SETUP_GUIDE.md` for detailed troubleshooting.
