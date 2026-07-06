#!/usr/bin/env python3
"""WebRunner - Desktop deployer for full-stack Python projects."""

import sys
import os

# Force UTF-8 for Windows console
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(__file__))

from backend.server import start_server

if __name__ == "__main__":
    start_server()
