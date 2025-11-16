"""
Centralized logging configuration for the backend.
This ensures consistent logging setup across the application and tests.
"""
import logging
import sys


def setup_logging():
    """
    Configure logging for the application.
    
    Uses basicConfig to set up:
    - Root logger level: INFO
    - Format: timestamp, level, name, message
    - Handler: StreamHandler to stdout
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )


def get_tp_logger():
    """
    Get a dedicated logger for TP/SL orders.
    
    Returns:
        Logger instance configured for TP/SL logging
    """
    return logging.getLogger("tp_orders")

