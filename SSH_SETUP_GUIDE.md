# SSH Access Configuration Guide for AWS

## Current Status

❌ **SSH connections are timing out to both AWS hosts:**
- Primary: `54.254.150.31`
- Alternative: `175.41.189.249`

## Possible Causes

1. **Security Group Configuration**
   - Port 22 (SSH) may not be open
   - Your IP address may not be whitelisted
   - Security group may only allow specific IPs

2. **Instance Status**
   - Instances may be stopped
   - Instances may have been terminated
   - IP addresses may have changed

3. **Network Configuration**
   - VPN or proxy required
   - Elastic IP may have changed
   - Instances may be in private subnet

## Configuration Options

### Option 1: Direct SSH (Preferred for Deployment)

#### Step 1: Verify Your SSH Key

```bash
# Check if key exists
ls -la ~/.ssh/id_rsa

# Verify permissions (should be 600)
chmod 600 ~/.ssh/id_rsa

# Test key format
ssh-keygen -l -f ~/.ssh/id_rsa
```

#### Step 2: Configure AWS Security Group

1. Go to AWS Console → EC2 → Security Groups
2. Find the security group for your instance
3. Edit Inbound Rules:
   - Type: SSH
   - Protocol: TCP
   - Port: 22
   - Source: Your IP address (or 0.0.0.0/0 for testing)
   - Description: "SSH access for deployment"

#### Step 3: Verify Instance Status

```bash
# Check if instances are running (via AWS CLI if available)
aws ec2 describe-instances \
  --instance-ids i-08726dc37133b2454 \
  --query 'Reservations[0].Instances[0].[State.Name,PublicIpAddress]' \
  --output table
```

#### Step 4: Test Connection

```bash
# Test with explicit key
ssh -i ~/.ssh/id_rsa -o ConnectTimeout=10 ubuntu@54.254.150.31

# Or use the test script
./test_aws_ssh.sh
```

### Option 2: AWS Session Manager (SSM)

If direct SSH is not available, you can use AWS Session Manager:

```bash
# Install Session Manager plugin
# macOS:
brew install session-manager-plugin

# Then connect:
aws ssm start-session --target i-08726dc37133b2454
```

However, Session Manager is interactive only and won't work with automated deployment scripts.

### Option 3: VPN/Bastion Host

If instances are in a private subnet, you may need:
- VPN connection
- Bastion host
- AWS Client VPN

## Quick Fix: Update IP Addresses

If the IP addresses have changed, update the deployment script:

```bash
# Find current instance IPs via AWS Console or CLI
# Then update deploy_decision_tracing_fix.sh with new IPs
```

## Alternative: Manual Deployment

If SSH access cannot be configured immediately, you can deploy manually:

1. **Use AWS Console EC2 Instance Connect** (browser-based)
2. **Upload files via S3**:
   ```bash
   # Upload files to S3
   aws s3 cp backend/app/api/routes_monitoring.py s3://your-bucket/
   # Then download on EC2 instance
   ```

3. **Use GitHub Actions** (if already configured):
   - Push code to repository
   - Let GitHub Actions deploy automatically

## Testing SSH Connection

Run the test script:
```bash
./test_aws_ssh.sh
```

Or test manually:
```bash
ssh -v -i ~/.ssh/id_rsa ubuntu@54.254.150.31
```

The `-v` flag provides verbose output to help diagnose connection issues.

## Next Steps

1. **Check AWS Console**:
   - Verify instances are running
   - Check Security Group rules
   - Note current public IP addresses

2. **Update Security Group**:
   - Add your current IP to SSH (port 22) rules
   - Or use 0.0.0.0/0 temporarily for testing

3. **Test Connection**:
   - Run `./test_aws_ssh.sh`
   - Or test manually with `ssh` command

4. **Once Connected**:
   - Run `./deploy_decision_tracing_fix.sh`
   - Or deploy manually using the steps in DEPLOYMENT_SUMMARY.md

## Troubleshooting

### Connection Timeout
- Check Security Group allows port 22
- Verify instance is running
- Check your firewall/network settings
- Try from different network (mobile hotspot)

### Permission Denied
- Verify SSH key is correct: `ssh-keygen -l -f ~/.ssh/id_rsa`
- Check key permissions: `chmod 600 ~/.ssh/id_rsa`
- Ensure public key is in `~/.ssh/authorized_keys` on server

### Host Key Verification Failed
- This is normal for first connection
- The scripts use `-o StrictHostKeyChecking=no` to bypass this
- Or manually add: `ssh-keyscan -H 54.254.150.31 >> ~/.ssh/known_hosts`
