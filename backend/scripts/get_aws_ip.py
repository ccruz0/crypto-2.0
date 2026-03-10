#!/usr/bin/env python3
"""
Get the current AWS instance public IP address.
This helps identify which IP needs to be whitelisted in Crypto.com Exchange.
"""
import requests
import sys
from typing import Optional

def _get_metadata_imdsv2(path: str) -> Optional[str]:
    """IMDSv2: PUT token, then GET path with token (works when IMDSv2 is required)."""
    try:
        token_resp = requests.put(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            timeout=2,
        )
        if token_resp.status_code != 200:
            return None
        token = token_resp.text.strip()
        meta_resp = requests.get(
            f"http://169.254.169.254/latest/meta-data/{path}",
            headers={"X-aws-ec2-metadata-token": token},
            timeout=2,
        )
        if meta_resp.status_code == 200:
            return meta_resp.text.strip()
    except Exception:
        pass
    return None


def get_public_ip():
    """Get the public IP address of the current instance"""
    try:
        # Try AWS metadata service (IMDSv2) first if running on EC2
        aws_ip = _get_metadata_imdsv2("public-ipv4")
        if aws_ip:
            print(f"🌐 AWS Instance Public IP: {aws_ip}")
            print(f"\n⚠️  IMPORTANT: This IP must be whitelisted in Crypto.com Exchange")
            print(f"   Go to: https://exchange.crypto.com/ → Settings → API Keys → Edit")
            print(f"   Add this IP to the whitelist: {aws_ip}")
            return aws_ip

        # Fallback to public IP service
        response = requests.get('https://api.ipify.org', timeout=5)
        public_ip = response.text.strip()
        print(f"🌐 Public IP Address: {public_ip}")
        print(f"\n⚠️  IMPORTANT: This IP must be whitelisted in Crypto.com Exchange")
        print(f"   Go to: https://exchange.crypto.com/ → Settings → API Keys → Edit")
        print(f"   Add this IP to the whitelist: {public_ip}")
        return public_ip
        
    except Exception as e:
        print(f"❌ Error getting IP address: {e}")
        return None

if __name__ == "__main__":
    print("\n" + "="*70)
    print("🌐 GETTING AWS PUBLIC IP ADDRESS")
    print("="*70 + "\n")
    
    ip = get_public_ip()
    
    if ip:
        print(f"\n✅ Your IP address: {ip}")
        print("\n📋 Next Steps:")
        print("1. Copy the IP address above")
        print("2. Go to https://exchange.crypto.com/ → Settings → API Keys")
        print("3. Edit your API key")
        print(f"4. Add {ip} to the IP whitelist")
        print("5. Save and wait 30 seconds")
        print("6. Restart backend: docker compose --profile aws restart backend-aws")
    else:
        print("\n❌ Could not determine IP address")
        sys.exit(1)
    
    print("\n" + "="*70 + "\n")

