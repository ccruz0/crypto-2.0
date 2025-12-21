#!/usr/bin/env python3
"""
Script para ejecutar el resumen diario manualmente
Uso: python3 scripts/send_daily_summary.py
"""
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.daily_summary import daily_summary_service
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        logger.info("🚀 Ejecutando resumen diario manualmente...")
        daily_summary_service.send_daily_summary()
        logger.info("✅ Resumen diario ejecutado exitosamente")
    except Exception as e:
        logger.error(f"❌ Error ejecutando resumen diario: {e}", exc_info=True)
        sys.exit(1)



















