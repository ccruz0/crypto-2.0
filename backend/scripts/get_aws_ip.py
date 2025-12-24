#!/usr/bin/env python3
"""
Get the current AWS instance public IP address.
This helps identify which IP needs to be whitelisted in Crypto.com Exchange.
"""
import requests
import sys

def get_public_ip():
    """Get the public IP address of the current instance"""
    try:
        # Try AWS metadata service first (if running on AWS)
        try:
            response = requests.get(
                'http://169.254.169.254/latest/meta-data/public-ipv4',
                timeout=2
            )
            if response.status_code == 200:
                aws_ip = response.text.strip()
                print(f"🌐 AWS Instance Public IP: {aws_ip}")
                print(f"\n⚠️  IMPORTANT: This IP must be whitelisted in Crypto.com Exchange")
                print(f"   Go to: https://exchange.crypto.com/ → Settings → API Keys → Edit")
                print(f"   Add this IP to the whitelist: {aws_ip}")
                return aws_ip
        except Exception:
            pass
        
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

