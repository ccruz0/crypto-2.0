#!/bin/sh
# Clean Next.js dev server processes and lock files

echo "🧹 Cleaning Next.js dev server..."

# Kill any existing Next.js dev processes
pkill -f "next dev" || echo "   No Next.js dev processes found"

# Remove lock files if they exist
if [ -f ".next" ]; then
  echo "   Removing .next directory..."
  rm -rf .next
fi

echo "✅ Clean complete"
