#!/usr/bin/env python3
"""
20_analysis.py — Analysis tools for imc4/
═══════════════════════════════════════════
Source: final/04_analysis.py, final/06_detection.py, final/02_data_ingest.py

Chain #34: bots          — Bot behavior analysis from CSV
Chain #54: bot-optimize  — Optimize against specific bot
Chain #60: sensitivity   — Parameter sensitivity analysis
Chain #49: p3p4-map      — P3→P4 product mapping
Chain #50: classify      — Classify unknown product
Chain #52: postmortem    — Post-mortem round analysis
Chain #53: parse-logs    — Parse submission logs
Chain #48: leaderboard   — Monitor leaderboard
Chain #56: sunlight      — Sunlight/humidity data analysis
Chain #57: voucher       — Voucher strike selection by IV
"""

import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

TRAINED_DIR = SCRIPT_DIR / "data" / "trained"


def cmd_bots(args=None):
    """Chain #34: Bot behavior analysis."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #34: Bot Behavior Analysis")
    print("═══════════════════════════════════════════════════════")

    # Use backtester to observe bot patterns
    from prosperity3bt.runner import run_backtest
    from prosperity3bt.file_reader import PackageResourcesReader
    from prosperity3bt.models import TradeMatchingMode
    from prosperity3bt.data import has_day_data

    import FinalTrader as ft
    ft.Logger.flush = lambda self, *a, **k: None
    ft.logger.log = lambda *a, **k: None
    ft.logger.print = lambda *a, **k: None

    reader = PackageResourcesReader()

    # Analyze trade logs for bot patterns
    print("\n[BOTS] Analyzing trade patterns from backtester data...")
    for r in [1, 3, 5]:
        for d in [0, 1]:
            try:
                if not has_day_data(reader, r, d):
                    continue
                trader = ft.Trader()
                result = run_backtest(
                    trader, reader, r, d,
                    print_output=False,
                    trade_matching_mode=TradeMatchingMode.worse,
                )
                if result.activity_logs:
                    n_trades = len([l for l in result.activity_logs
                                   if l.columns[0] == "TRADE"])
                    products = set(l.columns[2] for l in result.activity_logs)
                    print(f"  R{r}D{d}: {n_trades} trades, products: {products}")
            except Exception as e:
                print(f"  R{r}D{d}: Error — {e}")

    print("\n[BOTS] Analysis requires live P4 data for bot fingerprinting")
    return True


def cmd_bot_optimize(args=None):
    """Chain #54: Optimize against specific bot."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #54: Bot-Specific Optimization")
    print("═══════════════════════════════════════════════════════")
    print("\n  Requires live P4 data with identified bot patterns")
    print("  Use Chain #34 first to identify bots")
    return True


def cmd_sensitivity(args=None):
    """Chain #60: Sensitivity analysis."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #60: Sensitivity Analysis")
    print("═══════════════════════════════════════════════════════")

    import numpy as np
    from prosperity3bt.runner import run_backtest
    from prosperity3bt.file_reader import PackageResourcesReader
    from prosperity3bt.models import TradeMatchingMode
    from prosperity3bt.data import has_day_data

    import FinalTrader as ft
    ft.Logger.flush = lambda self, *a, **k: None
    ft.logger.log = lambda *a, **k: None
    ft.logger.print = lambda *a, **k: None

    # Import training infrastructure
    from importlib import import_module
    sys.path.insert(0, str(SCRIPT_DIR))

    # Load best params if available
    params_file = TRAINED_DIR / "best_params.json"
    if params_file.exists():
        base_params = json.loads(params_file.read_text())["params"]
        print(f"\n[SENS] Loaded best params from {params_file}")
    else:
        # Use defaults from 15_train
        from _15_train_params import get_defaults
        base_params = get_defaults()
        print("\n[SENS] Using default params")

    print("  Sensitivity analysis requires running backtest for each param variation")
    print("  This is a long-running operation")
    return True


def cmd_p3p4_map(args=None):
    """Chain #49: P3→P4 product mapping."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #49: P3→P4 Product Mapping")
    print("═══════════════════════════════════════════════════════")

    p3_products = {
        "RAINFOREST_RESIN": {"type": "stable", "fv": 10000, "limit": 50},
        "KELP": {"type": "volatile", "limit": 50},
        "SQUID_INK": {"type": "volatile", "limit": 50},
        "CROISSANTS": {"type": "basket_component", "limit": 250},
        "JAMS": {"type": "basket_component", "limit": 350},
        "DJEMBES": {"type": "basket_component", "limit": 60},
        "PICNIC_BASKET1": {"type": "basket", "limit": 60},
        "PICNIC_BASKET2": {"type": "basket", "limit": 100},
        "VOLCANIC_ROCK": {"type": "option_underlying", "limit": 400},
        "VOLCANIC_ROCK_VOUCHER_*": {"type": "option", "limit": 200},
        "MAGNIFICENT_MACARONS": {"type": "location_arb", "limit": 75},
    }

    print("\nP3 Products → Generic Strategy Mapping:")
    print(f"{'Product':35s} {'Type':20s} {'Strategy':30s} {'Limit':>5s}")
    print("-" * 95)

    strategy_map = {
        "stable": "Fixed FV market making",
        "volatile": "EMA/Kalman adaptive MM",
        "basket_component": "Hedge leg of basket arb",
        "basket": "Z-score basket arbitrage",
        "option_underlying": "Delta hedging",
        "option": "BSM IV arbitrage",
        "location_arb": "Conversion arbitrage",
    }

    for prod, info in p3_products.items():
        strategy = strategy_map.get(info["type"], "unknown")
        print(f"  {prod:33s} {info['type']:18s} {strategy:28s} {info['limit']:>5d}")

    print("\n  P4 products unknown until 14 April 2026")
    print("  Code is generic — handles any product through ProductRouter")
    return True


def cmd_classify(args=None):
    """Chain #50: Classify unknown product."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #50: Classify Unknown Product")
    print("═══════════════════════════════════════════════════════")
    print("\n  Classification algorithm:")
    print("  1. Observe first 200 ticks")
    print("  2. Calculate: volatility, mean-reversion (AC), spread, volume")
    print("  3. Classify into: stable / volatile / basket / option / conversion")
    print("  4. Select strategy automatically")
    print("\n  Requires live P4 data — built into FinalTrader.Trader")
    return True


def cmd_postmortem(args=None):
    """Chain #52: Post-mortem analysis."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #52: Post-mortem Round Analysis")
    print("═══════════════════════════════════════════════════════")
    print("\n  Requires submission logs from IMC")
    print("  Upload logs to data/p4_rounds/ and re-run")
    return True


def cmd_parse_logs(args=None):
    """Chain #53: Parse submission logs."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #53: Parse Submission Logs")
    print("═══════════════════════════════════════════════════════")

    from prosperity3bt.parse_submission_logs import parse

    logs_dir = SCRIPT_DIR / "data" / "p4_rounds"
    if not logs_dir.exists():
        print(f"\n  No logs in {logs_dir}")
        print("  Download from IMC and place in data/p4_rounds/")
        return True

    log_files = list(logs_dir.glob("*.log")) + list(logs_dir.glob("*.csv"))
    print(f"\n  Found {len(log_files)} log files")
    for lf in log_files:
        print(f"    {lf.name}")
    return True


def cmd_leaderboard(args=None):
    """Chain #48: Leaderboard monitoring."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #48: Leaderboard Monitor")
    print("═══════════════════════════════════════════════════════")
    print("\n  Leaderboard monitoring requires live competition access")
    print("  Available during IMC Prosperity 4 (14-30 April 2026)")
    return True


def cmd_sunlight(args=None):
    """Chain #56: Sunlight/humidity data."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #56: Sunlight & Humidity Analysis")
    print("═══════════════════════════════════════════════════════")
    print("\n  MAGNIFICENT_MACARONS conversion depends on:")
    print("    - sunlightIndex (ConversionObservation)")
    print("    - sugarPrice")
    print("    - transportFees, exportTariff, importTariff")
    print("\n  Analysis requires P4 round data with MACARONS product")
    return True


def cmd_voucher(args=None):
    """Chain #57: Voucher strike selection."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #57: Voucher Strike Selection by IV")
    print("═══════════════════════════════════════════════════════")
    print("\n  Strategy: trade vouchers with highest IV mispricing")
    print("  Strikes: 9500, 9750, 10000, 10250, 10500")
    print("  Model: BSM with empirical IV surface")
    print("  Built into FinalTrader — 11_strategy_options section")
    return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bots"
    commands = {
        "bots": cmd_bots,
        "bot-optimize": cmd_bot_optimize,
        "sensitivity": cmd_sensitivity,
        "p3p4-map": cmd_p3p4_map,
        "classify": cmd_classify,
        "postmortem": cmd_postmortem,
        "parse-logs": cmd_parse_logs,
        "leaderboard": cmd_leaderboard,
        "sunlight": cmd_sunlight,
        "voucher": cmd_voucher,
    }
    fn = commands.get(cmd)
    if fn is None:
        print(f"Unknown: {cmd}. Available: {', '.join(commands.keys())}")
        sys.exit(1)
    ok = fn(sys.argv[2:])
    sys.exit(0 if ok else 1)
