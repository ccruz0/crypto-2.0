#!/usr/bin/env python3
"""
Health Monitoring Script for Automated Trading Platform

This script monitors the health of critical services (containers and HTTP endpoints)
and sends Telegram notifications when issues are detected. It also attempts automatic
recovery by restarting failed services.

Usage:
    python3 infra/monitor_health.py

The script should be run via cron every 5 minutes:
    */5 * * * * cd /home/ubuntu/automated-trading-platform && /usr/bin/python3 infra/monitor_health.py >> /var/log/atp_health_monitor.log 2>&1
"""
import os
import sys
import subprocess
import time
import logging
import requests
from typing import List, Dict, Tuple, Optional
from datetime import datetime
import json

# Add parent directory to path to import telegram_helper
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from infra.telegram_helper import send_telegram_message

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Configuration
PROJECT_DIR = "/home/ubuntu/automated-trading-platform"
CRITICAL_SERVICES = ["backend-aws", "frontend-aws", "db", "gluetun"]
BACKEND_HEALTH_URL = "http://127.0.0.1:8002/health"
FRONTEND_HEALTH_URL = "http://127.0.0.1:3000"
HEALTH_CHECK_TIMEOUT = 30  # seconds (increased to handle database connection delays and slow responses)
RECOVERY_WAIT_SECONDS = 45  # Wait time after restart before re-checking (increased to allow full startup)
ENVIRONMENT = "AWS EC2 automated-trading-platform"
STATE_FILE = "/var/log/atp_health_monitor.state"  # File to track previous state
DOWN_THRESHOLD_MINUTES = 60  # Only notify if system has been down for more than 60 minutes (DRAMATICALLY REDUCED notifications)
ALERT_COOLDOWN_HOURS = 6  # Minimum hours between alerts for the same issue (prevents spam)
MAX_ALERTS_PER_DAY = 2  # Maximum number of down alerts per day (prevents notification fatigue)
ALERT_LOG_FILE = "/var/log/atp_health_monitor_alerts.log"  # File to track alert history


class HealthMonitor:
    """Monitor health of containers and HTTP endpoints"""
    
    def __init__(self, project_dir: str = PROJECT_DIR):
        self.project_dir = project_dir
        self.issues_found: List[str] = []
        self.services_restarted: List[str] = []
        self.previous_state_was_unhealthy = False
        
    def check_container_status(self, service_name: str) -> Tuple[bool, str]:
        """
        Check if a Docker container is running.
        
        Args:
            service_name: Name of the service to check
            
        Returns:
            Tuple of (is_healthy, status_message)
        """
        try:
            # Change to project directory and run docker compose ps
            result = subprocess.run(
                ["docker", "compose", "ps", "--format", "json", service_name],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                return False, f"docker compose ps failed: {result.stderr}"
            
            # Parse JSON output
            if not result.stdout.strip():
                return False, f"Service '{service_name}' not found"
            
            # docker compose ps can return multiple lines (one per container)
            lines = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
            if not lines:
                return False, f"Service '{service_name}' not found"
            
            # Check each container for this service
            for line in lines:
                try:
                    container_info = json.loads(line)
                    service = container_info.get("Service", "")
                    state = container_info.get("State", "").lower()
                    
                    if service == service_name:
                        if state == "running":
                            return True, f"Container '{service_name}' is running"
                        else:
                            return False, f"Container '{service_name}' is in state '{state}' (expected 'running')"
                except json.JSONDecodeError:
                    continue
            
            return False, f"Service '{service_name}' not found in docker compose ps output"
            
        except subprocess.TimeoutExpired:
            return False, f"Timeout checking container '{service_name}'"
        except Exception as e:
            logger.error(f"Error checking container '{service_name}': {e}", exc_info=True)
            return False, f"Error checking container: {str(e)}"
    
    def check_http_endpoint(self, url: str, name: str) -> Tuple[bool, str]:
        """
        Check if an HTTP endpoint is responding with 200 OK.
        
        Args:
            url: URL to check
            name: Friendly name for the endpoint
            
        Returns:
            Tuple of (is_healthy, status_message)
        """
        try:
            response = requests.get(url, timeout=HEALTH_CHECK_TIMEOUT, allow_redirects=True)
            if response.status_code == 200:
                return True, f"{name} endpoint responded with 200 OK"
            else:
                return False, f"{name} endpoint returned status {response.status_code} (expected 200)"
        except requests.exceptions.Timeout:
            # Don't immediately mark as down - backend might be slow but still working
            # Log warning but don't fail the check unless it's consistently timing out
            logger.warning(f"{name} endpoint timed out after {HEALTH_CHECK_TIMEOUT}s - this may be a temporary slowdown")
            return False, f"{name} endpoint timed out after {HEALTH_CHECK_TIMEOUT}s"
        except requests.exceptions.ConnectionError:
            return False, f"{name} endpoint connection refused"
        except Exception as e:
            logger.error(f"Error checking {name} endpoint: {e}", exc_info=True)
            return False, f"{name} endpoint error: {str(e)}"
    
    def restart_service(self, service_name: str) -> Tuple[bool, str]:
        """
        Restart a Docker Compose service.
        
        Args:
            service_name: Name of the service to restart
            
        Returns:
            Tuple of (success, message)
        """
        try:
            logger.info(f"Attempting to restart service '{service_name}'...")
            result = subprocess.run(
                ["docker", "compose", "restart", service_name],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                timeout=60
            )
            
            if result.returncode == 0:
                logger.info(f"Successfully restarted service '{service_name}'")
                return True, f"Service '{service_name}' restarted successfully"
            else:
                error_msg = result.stderr or result.stdout or "Unknown error"
                logger.error(f"Failed to restart '{service_name}': {error_msg}")
                return False, f"Failed to restart '{service_name}': {error_msg}"
                
        except subprocess.TimeoutExpired:
            return False, f"Timeout restarting service '{service_name}'"
        except Exception as e:
            logger.error(f"Error restarting service '{service_name}': {e}", exc_info=True)
            return False, f"Error restarting '{service_name}': {str(e)}"
    
    def check_all_services(self) -> Dict[str, Tuple[bool, str]]:
        """
        Check all critical services and endpoints.
        
        Returns:
            Dictionary mapping service/endpoint names to (is_healthy, message) tuples
        """
        results = {}
        
        # Check containers
        for service in CRITICAL_SERVICES:
            is_healthy, message = self.check_container_status(service)
            results[f"container:{service}"] = (is_healthy, message)
            if not is_healthy:
                self.issues_found.append(f"{service}: {message}")
        
        # Check backend health endpoint
        is_healthy, message = self.check_http_endpoint(BACKEND_HEALTH_URL, "Backend")
        results["endpoint:backend"] = (is_healthy, message)
        if not is_healthy:
            self.issues_found.append(f"Backend endpoint: {message}")
        
        # Check frontend health endpoint
        is_healthy, message = self.check_http_endpoint(FRONTEND_HEALTH_URL, "Frontend")
        results["endpoint:frontend"] = (is_healthy, message)
        if not is_healthy:
            self.issues_found.append(f"Frontend endpoint: {message}")
        
        return results
    
    def attempt_recovery(self, failed_services: List[str]) -> Dict[str, Tuple[bool, str]]:
        """
        Attempt to recover failed services by restarting them.
        
        Args:
            failed_services: List of service names that failed
            
        Returns:
            Dictionary mapping service names to (success, message) tuples
        """
        recovery_results = {}
        
        # Determine which containers to restart based on failed services
        services_to_restart = []
        
        for failed in failed_services:
            # Extract service name from failed check
            if failed.startswith("container:"):
                service_name = failed.replace("container:", "").split(":")[0]
                if service_name in CRITICAL_SERVICES:
                    services_to_restart.append(service_name)
            elif failed.startswith("Backend endpoint:"):
                # Backend endpoint failed, restart backend-aws
                if "backend-aws" not in services_to_restart:
                    services_to_restart.append("backend-aws")
            elif failed.startswith("Frontend endpoint:"):
                # Frontend endpoint failed, restart frontend-aws
                if "frontend-aws" not in services_to_restart:
                    services_to_restart.append("frontend-aws")
        
        # Remove duplicates
        services_to_restart = list(set(services_to_restart))
        
        # Restart services
        for service in services_to_restart:
            success, message = self.restart_service(service)
            recovery_results[service] = (success, message)
            if success:
                self.services_restarted.append(service)
        
        return recovery_results
    
    def load_previous_state(self) -> Tuple[bool, Optional[datetime], bool]:
        """
        Load previous health state from state file.
        
        Returns:
            Tuple of (was_unhealthy, first_down_time, alert_sent)
            - was_unhealthy: True if previous state was unhealthy, False otherwise
            - first_down_time: datetime when system first went down, or None if healthy
            - alert_sent: True if alert was already sent, False otherwise
        """
        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, 'r') as f:
                    content = f.read().strip()
                    if content == "unhealthy":
                        # Old format - no timestamp, assume it's been down for a while
                        return True, datetime.now(), False
                    elif content.startswith("unhealthy:"):
                        # New format with timestamp and optional alert flag
                        parts = content.split(":", 2)
                        try:
                            timestamp_str = parts[1]
                            first_down_time = datetime.fromisoformat(timestamp_str)
                            alert_sent = len(parts) > 2 and parts[2] == "alert_sent"
                            return True, first_down_time, alert_sent
                        except (ValueError, IndexError):
                            logger.warning(f"Could not parse timestamp from state file: {content}")
                            return True, datetime.now(), False
                    else:
                        return False, None, False
        except Exception as e:
            logger.warning(f"Could not load previous state: {e}")
        return False, None, False
    
    def save_state(self, is_healthy: bool, first_down_time: Optional[datetime] = None, alert_sent: bool = False):
        """
        Save current health state to state file.
        
        Args:
            is_healthy: Whether all services are currently healthy
            first_down_time: datetime when system first went down (only used if is_healthy=False)
            alert_sent: Whether alert was already sent (only used if is_healthy=False)
        """
        try:
            if is_healthy:
                state = "healthy"
            else:
                # Save unhealthy state with timestamp and alert flag
                if first_down_time:
                    alert_flag = ":alert_sent" if alert_sent else ""
                    state = f"unhealthy:{first_down_time.isoformat()}{alert_flag}"
                else:
                    # If no timestamp provided, use current time
                    alert_flag = ":alert_sent" if alert_sent else ""
                    state = f"unhealthy:{datetime.now().isoformat()}{alert_flag}"
            with open(STATE_FILE, 'w') as f:
                f.write(state)
        except Exception as e:
            logger.warning(f"Could not save state: {e}")
    
    def format_alert_message(self, is_recovery: bool = False, recovery_success: Optional[bool] = None, is_auto_recovery: bool = False) -> str:
        """
        Format a Telegram alert message.
        
        Args:
            is_recovery: Whether this is a recovery notification
            recovery_success: Whether recovery was successful (only used if is_recovery=True)
            is_auto_recovery: Whether this is an automatic recovery (system recovered by itself)
            
        Returns:
            Formatted message string
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        if is_recovery:
            if recovery_success:
                emoji = "✅"
                title = "APP RECOVERED"
                if is_auto_recovery:
                    body = "All checks OK - system recovered automatically."
                else:
                    body = "All checks OK after automatic restart."
            else:
                emoji = "❌"
                title = "APP STILL DOWN"
                body = "Automatic restart attempt did not resolve the issues."
        else:
            emoji = "⚠️"
            title = "APP DOWN"
            body = "Failure detected in containers/endpoints."
        
        message = f"{emoji} <b>{title}</b>\n\n"
        message += f"🕐 Timestamp: {timestamp}\n"
        message += f"🌐 Environment: {ENVIRONMENT}\n\n"
        message += f"{body}\n\n"
        
        if self.issues_found:
            message += "<b>Issues detected:</b>\n"
            for issue in self.issues_found:
                message += f"  • {issue}\n"
            message += "\n"
        
        if self.services_restarted:
            message += "<b>Services restarted:</b>\n"
            for service in self.services_restarted:
                message += f"  • {service}\n"
            message += "\n"
        
        return message
    
    def run(self) -> int:
        """
        Run the health monitoring check.
        
        Returns:
            Exit code (0 if all healthy, 1 if issues found)
        """
        try:
            logger.info("Starting health check...")
            
            # Load previous state to detect recovery
            self.previous_state_was_unhealthy, first_down_time, alert_already_sent = self.load_previous_state()
            
            # Check all services
            results = self.check_all_services()
            
            # Log detailed results
            logger.info("=== Health Check Results ===")
            for name, (is_healthy, message) in results.items():
                status_icon = "✅" if is_healthy else "❌"
                logger.info(f"{status_icon} {name}: {message}")
            
            # Check if any issues were found
            all_healthy = all(is_healthy for is_healthy, _ in results.values())
            
            # If system is healthy now but was unhealthy before, send recovery notification
            # BUT ONLY if we previously sent a down alert (alert_already_sent = True)
            if all_healthy and self.previous_state_was_unhealthy:
                # Only send recovery notification if we previously sent a down alert
                if alert_already_sent:
                    logger.info("System recovered automatically - sending recovery notification (down alert was previously sent)")
                    recovery_message = self.format_alert_message(
                        is_recovery=True, 
                        recovery_success=True, 
                        is_auto_recovery=True
                    )
                    telegram_sent = send_telegram_message(recovery_message)
                    if telegram_sent:
                        logger.info("Auto-recovery notification sent to Telegram")
                    else:
                        logger.warning("Failed to send auto-recovery notification to Telegram")
                else:
                    logger.info("System recovered automatically but no down alert was sent (recovered before 5 min threshold) - skipping recovery notification")
                # Save healthy state
                self.save_state(True)
                return 0
            
            if all_healthy:
                logger.info("All services are healthy - no action needed")
                # Save healthy state
                self.save_state(True)
                return 0
            
            # Issues found - check if we should send alert
            logger.warning(f"Health check failed: {len(self.issues_found)} issue(s) detected")
            
            # Determine when system first went down
            current_time = datetime.now()
            if not self.previous_state_was_unhealthy:
                # New failure - record current time as first down time
                first_down_time = current_time
                alert_already_sent = False  # Reset alert flag for new failure
                logger.info(f"System just went down - recording timestamp: {first_down_time.isoformat()}")
            else:
                # System was already down - use previous timestamp
                if first_down_time is None:
                    # Shouldn't happen, but fallback to current time
                    first_down_time = current_time
                    alert_already_sent = False
                logger.info(f"System still down - first detected at: {first_down_time.isoformat()}, alert_sent={alert_already_sent}")
            
            # Calculate how long system has been down
            time_down = current_time - first_down_time
            minutes_down = time_down.total_seconds() / 60
            
            # Only send alert if:
            # 1. System has been down for more than threshold
            # 2. Alert hasn't been sent yet
            should_send_alert = minutes_down > DOWN_THRESHOLD_MINUTES and not alert_already_sent
            
            if should_send_alert:
                # First time we're sending the alert (after threshold)
                logger.info(f"System has been down for {minutes_down:.1f} minutes - sending alert")
                alert_message = self.format_alert_message(is_recovery=False)
                alert_message += f"\n⏱️ System has been down for {minutes_down:.1f} minutes"
                telegram_sent = send_telegram_message(alert_message)
                if telegram_sent:
                    logger.info("Alert sent to Telegram")
                    alert_already_sent = True  # Mark alert as sent
                else:
                    logger.warning("Failed to send alert to Telegram")
            elif alert_already_sent:
                logger.info(f"System still down ({minutes_down:.1f} minutes) - alert already sent, will send recovery notification if system recovers")
            else:
                logger.info(f"System down for {minutes_down:.1f} minutes (threshold: {DOWN_THRESHOLD_MINUTES} min) - not sending alert yet")
            
            # Save unhealthy state with timestamp and alert flag
            self.save_state(False, first_down_time, alert_already_sent)
            
            # Attempt recovery
            logger.info("Attempting automatic recovery...")
            recovery_results = self.attempt_recovery(self.issues_found)
            
            # Wait for services to start
            if self.services_restarted:
                logger.info(f"Waiting {RECOVERY_WAIT_SECONDS} seconds for services to start...")
                time.sleep(RECOVERY_WAIT_SECONDS)
            
            # Re-check after recovery
            logger.info("Re-checking services after recovery attempt...")
            self.issues_found.clear()  # Clear previous issues
            post_recovery_results = self.check_all_services()
            
            # Check if recovery was successful
            recovery_successful = all(is_healthy for is_healthy, _ in post_recovery_results.values())
            
            # Send recovery notification ONLY if we previously sent a down alert
            if alert_already_sent:
                recovery_message = self.format_alert_message(
                    is_recovery=True, 
                    recovery_success=recovery_successful,
                    is_auto_recovery=False
                )
                telegram_sent = send_telegram_message(recovery_message)
                if telegram_sent:
                    logger.info("Recovery notification sent to Telegram")
                else:
                    logger.warning("Failed to send recovery notification to Telegram")
            else:
                logger.info("Recovery attempted but no down alert was sent (recovered before 5 min threshold) - skipping recovery notification")
            
            if recovery_successful:
                logger.info("Recovery successful - all services are now healthy")
                # Save healthy state
                self.save_state(True)
                return 0
            else:
                logger.error("Recovery failed - some services are still unhealthy")
                # Save unhealthy state
                self.save_state(False)
                return 1
                
        except Exception as e:
            logger.error(f"Fatal error in health monitor: {e}", exc_info=True)
            # Try to send error notification
            error_message = (
                f"❌ <b>HEALTH MONITOR ERROR</b>\n\n"
                f"🕐 Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
                f"🌐 Environment: {ENVIRONMENT}\n\n"
                f"The health monitoring script failed with error:\n"
                f"<code>{str(e)}</code>"
            )
            send_telegram_message(error_message)
            return 1


def main():
    """Main entry point"""
    # Ensure we're in the project directory
    if not os.path.exists(PROJECT_DIR):
        logger.error(f"Project directory not found: {PROJECT_DIR}")
        sys.exit(1)
    
    monitor = HealthMonitor()
    exit_code = monitor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

