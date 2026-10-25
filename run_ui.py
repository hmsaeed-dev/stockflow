#!/usr/bin/env python3
"""
Convenience launcher for StockFlow Streamlit UI.
Usage:
    python run_ui.py
"""
import sys
import subprocess
from pathlib import Path

if __name__ == "__main__":
    app_path = Path(__file__).resolve().parent / "stockflow-script" / "app.py"
    cmd = [sys.executable, "-m", "streamlit", "run", str(app_path)]
    print(f"Launching StockFlow UI: {' '.join(cmd)}")
    subprocess.run(cmd)
