#!/usr/bin/env python3
"""WebRunner - Desktop deployer for full-stack Python projects."""

import sys
import os

# Force UTF-8 for Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except:
        pass

sys.path.insert(0, os.path.dirname(__file__))

print()
print("=" * 56)
print("  WebRunner - Starting...")
print("=" * 56)
print()

# Check dependencies
missing = []
for mod in ("fastapi", "uvicorn", "httpx", "pydantic"):
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)

if missing:
    print("ERROR: Missing Python packages:", ", ".join(missing))
    print("Install them with:")
    print(f"  pip install {' '.join(missing)}")
    input("\nPress Enter to exit...")
    sys.exit(1)

try:
    from backend.server import start_server
    start_server()
except KeyboardInterrupt:
    print("\nWebRunner stopped.")
except Exception as e:
    print(f"\nERROR: {e}")
    import traceback
    traceback.print_exc()
    input("\nPress Enter to exit...")
