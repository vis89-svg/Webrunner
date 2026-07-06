#!/usr/bin/env python3
"""WebRunner - Desktop deployer for full-stack Python projects."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from backend.server import start_server

if __name__ == "__main__":
    start_server()
