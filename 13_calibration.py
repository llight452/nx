#!/usr/bin/env python3
"""
13_calibration.py — Online recalibration for imc4/
═══════════════════════════════════════════════════════
Chain #51: Calibrate on live data between rounds
Source: final/FinalTrader.py CalibrationEngine
"""

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def main():
    print("═══════════════════════════════════════════════════════")
    print(" Chain #51: Online Calibration")
    print("═══════════════════════════════════════════════════════")
    print("\n  Calibration is built into FinalTrader.Trader:")
    print("    - CalibrationEngine (online recalibration)")
    print("    - EMA alpha auto-tuning per product")
    print("    - Regime detection → strategy switch")
    print("\n  Runs automatically during live trading")
    print("  Manual trigger requires P4 live data")


if __name__ == "__main__":
    main()
