#!/usr/bin/env python3
"""
Debug CSV parsing
"""

import csv

def debug_csv(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        # Skip header lines
        for i in range(4):  # Skip disclaimer, export info, and empty line
            line = next(file)
            print(f"Line {i+1}: {line.strip()}")
        
        print("\n--- CSV Reader ---")
        reader = csv.DictReader(file, quotechar='"', delimiter=',')
        
        print(f"Fieldnames: {reader.fieldnames}")
        
        for i, row in enumerate(reader):
            print(f"\nRow {i+1}:")
            for key, value in row.items():
                print(f"  {key}: {value}")
            if i >= 2:  # Only show first 3 rows
                break

if __name__ == "__main__":
    print("=== Open Orders CSV ===")
    debug_csv("/Users/carloscruz/Desktop/novale/open-orders.csv")
    
    print("\n\n=== Trigger Orders CSV ===")
    debug_csv("/Users/carloscruz/Desktop/novale/trigger-orders.csv")
