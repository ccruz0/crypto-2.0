#!/usr/bin/env python3
"""
Script para limpiar la tabla de assets y reimportar solo los datos correctos
"""

import sqlite3
import os

def clear_assets():
    db_path = os.path.join(os.path.dirname(__file__), 'assets.db')
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Limpiar la tabla de assets
    cursor.execute("DELETE FROM assets")
    conn.commit()
    
    print("✅ Tabla de assets limpiada")
    
    # Mostrar el estado actual
    cursor.execute("SELECT COUNT(*) FROM assets")
    count = cursor.fetchone()[0]
    print(f"📊 Assets restantes: {count}")
    
    conn.close()

if __name__ == "__main__":
    clear_assets()

