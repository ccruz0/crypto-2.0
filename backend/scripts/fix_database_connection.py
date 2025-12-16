#!/usr/bin/env python3
"""
Diagnostic and fix script for database connection issues.
This script helps identify and resolve "could not translate host name 'db'" errors.
"""

import os
import sys
import socket
import subprocess
from urllib.parse import urlparse

def check_docker_compose_running():
    """Check if docker-compose is available and services are running."""
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            containers = result.stdout.strip().split("\n")
            db_container = any("postgres" in c.lower() or c == "postgres_hardened" for c in containers)
            backend_container = any("backend" in c.lower() for c in containers)
            return {
                "available": True,
                "db_running": db_container,
                "backend_running": backend_container,
                "containers": containers
            }
    except Exception as e:
        print(f"⚠️  Could not check Docker containers: {e}")
    
    return {"available": False, "db_running": False, "backend_running": False, "containers": []}

def check_hostname_resolution(hostname="db"):
    """Check if hostname can be resolved."""
    try:
        ip = socket.gethostbyname(hostname)
        return {"resolvable": True, "ip": ip}
    except socket.gaierror:
        return {"resolvable": False, "ip": None}

def check_database_url():
    """Check DATABASE_URL environment variable."""
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        return {"set": False, "url": None, "hostname": None}
    
    parsed = urlparse(database_url)
    return {
        "set": True,
        "url": database_url.split("@")[-1] if "@" in database_url else database_url,  # Hide credentials
        "hostname": parsed.hostname,
        "port": parsed.port
    }

def test_database_connection():
    """Test actual database connection."""
    try:
        # Add parent directory to path to import app modules
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from app.database import test_database_connection, engine
        
        if engine is None:
            return {"success": False, "message": "Database engine is not configured"}
        
        success, message = test_database_connection()
        return {"success": success, "message": message}
    except Exception as e:
        return {"success": False, "message": f"Error testing connection: {str(e)}"}

def suggest_fix(diagnostics):
    """Suggest fixes based on diagnostics."""
    suggestions = []
    
    if not diagnostics["docker"]["available"]:
        suggestions.append("❌ Docker is not available or not running")
        return suggestions
    
    if not diagnostics["docker"]["db_running"]:
        suggestions.append("🔧 FIX: Database container is not running")
        suggestions.append("   Run: docker-compose --profile aws up -d db")
    
    if not diagnostics["hostname"]["resolvable"]:
        suggestions.append("🔧 FIX: Hostname 'db' cannot be resolved")
        if diagnostics["docker"]["db_running"]:
            suggestions.append("   The database container is running but hostname resolution failed")
            suggestions.append("   This might indicate a Docker network issue")
            suggestions.append("   Try: docker-compose --profile aws restart db backend-aws")
        else:
            suggestions.append("   Start the database container first: docker-compose --profile aws up -d db")
    
    if not diagnostics["database_url"]["set"]:
        suggestions.append("🔧 FIX: DATABASE_URL environment variable is not set")
        suggestions.append("   Check your .env.aws file or docker-compose.yml")
    
    if diagnostics["database_url"]["hostname"] == "db" and not diagnostics["hostname"]["resolvable"]:
        if diagnostics["docker"]["db_running"]:
            suggestions.append("🔧 FIX: Database is running but hostname 'db' not resolvable")
            suggestions.append("   This might work inside Docker containers but not from host")
            suggestions.append("   If running backend outside Docker, use 'localhost' instead")
    
    if not diagnostics["connection"]["success"]:
        suggestions.append("🔧 FIX: Database connection test failed")
        suggestions.append(f"   Error: {diagnostics['connection']['message']}")
        if "could not translate host name" in diagnostics["connection"]["message"].lower():
            suggestions.append("   Ensure database container is running and on same Docker network")
            suggestions.append("   Run: docker-compose --profile aws up -d")
    
    return suggestions

def main():
    """Run diagnostics and suggest fixes."""
    print("=" * 60)
    print("Database Connection Diagnostic Tool")
    print("=" * 60)
    print()
    
    # Run diagnostics
    print("🔍 Running diagnostics...")
    print()
    
    docker_status = check_docker_compose_running()
    hostname_status = check_hostname_resolution()
    db_url_status = check_database_url()
    connection_status = test_database_connection()
    
    diagnostics = {
        "docker": docker_status,
        "hostname": hostname_status,
        "database_url": db_url_status,
        "connection": connection_status
    }
    
    # Display results
    print("📊 Diagnostic Results:")
    print()
    
    print(f"  Docker Status:")
    print(f"    Available: {'✅' if docker_status['available'] else '❌'}")
    if docker_status['available']:
        print(f"    DB Container Running: {'✅' if docker_status['db_running'] else '❌'}")
        print(f"    Backend Container Running: {'✅' if docker_status['backend_running'] else '❌'}")
        if docker_status['containers']:
            print(f"    Running Containers: {', '.join(docker_status['containers'][:5])}")
    print()
    
    print(f"  Hostname Resolution ('db'):")
    print(f"    Resolvable: {'✅' if hostname_status['resolvable'] else '❌'}")
    if hostname_status['resolvable']:
        print(f"    IP Address: {hostname_status['ip']}")
    print()
    
    print(f"  DATABASE_URL:")
    print(f"    Set: {'✅' if db_url_status['set'] else '❌'}")
    if db_url_status['set']:
        print(f"    Hostname: {db_url_status['hostname']}")
        print(f"    Port: {db_url_status['port']}")
        print(f"    URL: {db_url_status['url']}")
    print()
    
    print(f"  Database Connection Test:")
    print(f"    Success: {'✅' if connection_status['success'] else '❌'}")
    print(f"    Message: {connection_status['message']}")
    print()
    
    # Suggest fixes
    suggestions = suggest_fix(diagnostics)
    
    if suggestions:
        print("=" * 60)
        print("🔧 Suggested Fixes:")
        print("=" * 60)
        for suggestion in suggestions:
            print(f"  {suggestion}")
        print()
        
        # Ask if user wants to apply fixes
        if docker_status['available'] and not docker_status['db_running']:
            print("💡 Quick Fix Available:")
            print("   Would you like to start the database container? (y/n): ", end="")
            try:
                response = input().strip().lower()
                if response == 'y':
                    print("\n🚀 Starting database container...")
                    result = subprocess.run(
                        ["docker-compose", "--profile", "aws", "up", "-d", "db"],
                        cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                        timeout=30
                    )
                    if result.returncode == 0:
                        print("✅ Database container started successfully!")
                        print("   You may need to restart the backend: docker-compose --profile aws restart backend-aws")
                    else:
                        print("❌ Failed to start database container")
            except (KeyboardInterrupt, EOFError):
                print("\n   Skipped.")
            except Exception as e:
                print(f"\n❌ Error: {e}")
    else:
        print("=" * 60)
        print("✅ All checks passed! Database connection should be working.")
        print("=" * 60)
    
    print()

if __name__ == "__main__":
    main()
