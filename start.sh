#!/bin/bash

echo ""
echo "  ⚔️  Then is starting..."
echo ""

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "  ✗ Python 3 not found."
    echo "  Install it from https://python.org/downloads"
    exit 1
fi

# Open browser after 2s
(sleep 2 && open "http://localhost:3000" 2>/dev/null || xdg-open "http://localhost:3000" 2>/dev/null) &

echo "  ✓ Server running at http://localhost:3000"
echo "  ✓ Opening your browser..."
echo ""
echo "  Press Ctrl+C to stop Then."
echo ""

python3 server.py
