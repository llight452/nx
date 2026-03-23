#!/usr/bin/env python3
"""
14_trader.py — Live trading operations for imc4/
═══════════════════════════════════════════════════
Chain #21: round-start  — 90-second round start protocol
Chain #22: adapt        — Adapt strategy to new round
Chain #55: multi-round  — Multi-round cumulative strategy
"""

import json
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))


def cmd_round_start(args=None):
    """Chain #21: Round-start protocol (90 seconds)."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #21: Round-Start Protocol (90s)")
    print("═══════════════════════════════════════════════════════")

    narrative = ""
    if args:
        for i, a in enumerate(args):
            if a == "--narrative" and i + 1 < len(args):
                narrative = args[i + 1]

    print(f"\n[ROUND-START] Protocol:")
    print(f"  1. Read narrative → identify products + mechanics")
    print(f"  2. Map to strategy (narrative decoder)")
    print(f"  3. Load best params or use defaults")
    print(f"  4. Deploy FinalTrader.py to IMC")
    print(f"  5. Monitor first 200 ticks for calibration")

    if narrative:
        print(f"\n  Narrative: {narrative[:200]}")
        # Could call narrative decoder here

    print(f"\n  Time budget: 90 seconds")
    print(f"  FinalTrader auto-handles product classification")
    return True


def cmd_adapt(args=None):
    """Chain #22: Adapt strategy to current round."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #22: Strategy Adaptation")
    print("═══════════════════════════════════════════════════════")
    print(f"\n  FinalTrader has built-in adaptation:")
    print(f"    - RegimeDetector8 (8-state FSM)")
    print(f"    - BotFingerprinter (detect opponent strategies)")
    print(f"    - CalibrationEngine (online parameter tuning)")
    print(f"    - ProductRouter (auto-assign strategy per product)")
    print(f"\n  Manual adaptation: edit FinalTrader class constants")
    return True


def cmd_multi_round(args=None):
    """Chain #55: Multi-round cumulative strategy."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #55: Multi-Round Cumulative")
    print("═══════════════════════════════════════════════════════")
    print(f"\n  Strategy accumulates across rounds:")
    print(f"    - traderData persists state between days")
    print(f"    - Best params from previous rounds loaded")
    print(f"    - Bot patterns cached for recognition")
    print(f"\n  Built into FinalTrader.dump_state/load_state")
    return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "round-start"
    commands = {
        "round-start": cmd_round_start,
        "adapt": cmd_adapt,
        "multi-round": cmd_multi_round,
    }
    fn = commands.get(cmd)
    if fn is None:
        print(f"Unknown: {cmd}")
        sys.exit(1)
    ok = fn(sys.argv[2:])
    sys.exit(0 if ok else 1)
