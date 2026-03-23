#!/usr/bin/env python3
"""
16_backtest.py — Backtesting engine for imc4/
═══════════════════════════════════════════════
Source: final/train.py (backtesting parts) + final/11_backtesting.py

Chain #7:  baseline  — run FinalTrader defaults on all days
Chain #37: smoke     — run 1 day, check it doesn't crash
Chain #8:  run-day   — run specific round/day
Chain #9:  run-all   — run all CSV days
Chain #12: ab-test   — compare two traders
Chain #59: parallel  — parallel backtest multiple configs
"""

import copy
import json
import os
import random
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# ═══════════════════════════════════════════════════════════════════
# Setup paths
# ═══════════════════════════════════════════════════════════════════
SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from prosperity3bt.runner import run_backtest
from prosperity3bt.file_reader import PackageResourcesReader
from prosperity3bt.models import TradeMatchingMode
from prosperity3bt.data import has_day_data

# ═══════════════════════════════════════════════════════════════════
# Import FinalTrader + patch for backtesting
# ═══════════════════════════════════════════════════════════════════
import FinalTrader as ft

ft.Logger.flush = lambda self, *a, **k: None
if hasattr(ft, 'Logger_full'):
    ft.Logger_full.flush = lambda self, *a, **k: None

_orig_log = getattr(ft.logger, 'log', None)
_orig_print = getattr(ft.logger, 'print', None)
ft.logger.log = lambda *a, **k: None
ft.logger.print = lambda *a, **k: None

if hasattr(ft, 'timeout_guard'):
    ft.timeout_guard.start = lambda: None
    ft.timeout_guard.check = lambda: None

ft.CONFIG["PROFILE_EVERY"] = 999999

TRAINED_DIR = SCRIPT_DIR / "data" / "trained"
RESULTS_FILE = TRAINED_DIR / "backtest_results.json"


# ═══════════════════════════════════════════════════════════════════
# Day discovery
# ═══════════════════════════════════════════════════════════════════
def discover_days() -> List[Tuple[int, int]]:
    reader = PackageResourcesReader()
    days = []
    for r in range(0, 10):
        for d in range(-5, 15):
            try:
                if has_day_data(reader, r, d):
                    days.append((r, d))
            except Exception:
                pass
    return days


# ═══════════════════════════════════════════════════════════════════
# PnL extraction
# ═══════════════════════════════════════════════════════════════════
def extract_pnl(result) -> float:
    if not result.activity_logs:
        return 0.0
    last_ts = max(log.columns[1] for log in result.activity_logs)
    total = sum(
        float(log.columns[16])
        for log in result.activity_logs
        if log.columns[1] == last_ts
    )
    return total


def extract_pnl_by_product(result) -> Dict[str, float]:
    if not result.activity_logs:
        return {}
    last_ts = max(log.columns[1] for log in result.activity_logs)
    pnl_by_product = {}
    for log in result.activity_logs:
        if log.columns[1] == last_ts:
            product = log.columns[2]
            pnl = float(log.columns[16])
            pnl_by_product[product] = pnl
    return pnl_by_product


# ═══════════════════════════════════════════════════════════════════
# Single day runner
# ═══════════════════════════════════════════════════════════════════
def run_single_day(round_num: int, day_num: int, trader_cls=None, verbose: bool = True) -> Dict:
    if trader_cls is None:
        trader_cls = ft.Trader

    t0 = time.time()
    try:
        trader = trader_cls()
        result = run_backtest(
            trader,
            PackageResourcesReader(),
            round_num=round_num,
            day_num=day_num,
            print_output=False,
            trade_matching_mode=TradeMatchingMode.worse,
            no_names=False,
            show_progress_bar=False,
        )
        pnl = extract_pnl(result)
        pnl_by_product = extract_pnl_by_product(result)
        elapsed = time.time() - t0

        if verbose:
            print(f"  R{round_num}D{day_num}: PnL={pnl:,.0f}  ({elapsed:.1f}s)  {pnl_by_product}", flush=True)

        return {
            "round": round_num,
            "day": day_num,
            "pnl": pnl,
            "pnl_by_product": pnl_by_product,
            "elapsed": elapsed,
            "ok": True,
        }
    except Exception as e:
        elapsed = time.time() - t0
        if verbose:
            print(f"  R{round_num}D{day_num}: ERROR — {e}  ({elapsed:.1f}s)", flush=True)
        return {
            "round": round_num,
            "day": day_num,
            "pnl": 0.0,
            "error": str(e),
            "elapsed": elapsed,
            "ok": False,
        }


# ═══════════════════════════════════════════════════════════════════
# Commands
# ═══════════════════════════════════════════════════════════════════

def cmd_baseline(args=None):
    """Chain #7: Baseline backtest — FinalTrader defaults on all days."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #7: Baseline Backtest")
    print("═══════════════════════════════════════════════════════")

    days = discover_days()
    print(f"\n[BASELINE] {len(days)} days available: {days}\n")

    results = []
    total_pnl = 0.0
    for i, (r, d) in enumerate(days):
        res = run_single_day(r, d)
        results.append(res)
        total_pnl += res["pnl"]
        print(f"  Cumulative: {total_pnl:,.0f}  [{i+1}/{len(days)}]", flush=True)

    mean_pnl = total_pnl / len(days) if days else 0
    print(f"\n{'='*60}")
    print(f"[BASELINE] Total PnL: {total_pnl:,.0f}")
    print(f"[BASELINE] Mean PnL/day: {mean_pnl:,.0f}")
    print(f"[BASELINE] Days: {len(days)}")

    # Breakdown by product
    product_totals: Dict[str, float] = {}
    for r in results:
        for prod, pnl in r.get("pnl_by_product", {}).items():
            product_totals[prod] = product_totals.get(prod, 0) + pnl
    print(f"\nProduct breakdown:")
    for prod in sorted(product_totals, key=lambda p: product_totals[p], reverse=True):
        print(f"  {prod:30s}: {product_totals[prod]:,.0f}")

    # Save
    TRAINED_DIR.mkdir(parents=True, exist_ok=True)
    save_data = {
        "type": "baseline",
        "total_pnl": total_pnl,
        "mean_pnl": mean_pnl,
        "n_days": len(days),
        "product_totals": product_totals,
        "per_day": [{"round": r["round"], "day": r["day"], "pnl": r["pnl"]} for r in results],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    RESULTS_FILE.write_text(json.dumps(save_data, indent=2))
    print(f"\nSaved → {RESULTS_FILE}")

    return True


def cmd_smoke(args=None):
    """Chain #37: Smoke test — 1 day, check no crash."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #37: Smoke Test")
    print("═══════════════════════════════════════════════════════")

    days = discover_days()
    if not days:
        print("[ERROR] No backtester days found!")
        return False

    r, d = days[0]
    print(f"\n[SMOKE] Running R{r}D{d}...")
    res = run_single_day(r, d)

    if res["ok"]:
        print(f"\n  ✓ SMOKE PASS — PnL={res['pnl']:,.0f}  ({res['elapsed']:.1f}s)")
        return True
    else:
        print(f"\n  ✗ SMOKE FAIL — {res.get('error', 'unknown')}")
        return False


def cmd_run_day(args=None):
    """Chain #8: Run specific round/day."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #8: Run Specific Day")
    print("═══════════════════════════════════════════════════════")

    # Parse --round N --day N from args
    round_num = 1
    day_num = 0
    if args:
        for i, a in enumerate(args):
            if a == "--round" and i + 1 < len(args):
                round_num = int(args[i + 1])
            if a == "--day" and i + 1 < len(args):
                day_num = int(args[i + 1])

    print(f"\n[RUN] R{round_num}D{day_num}...")
    res = run_single_day(round_num, day_num)

    if res["ok"]:
        print(f"\n  ✓ PnL={res['pnl']:,.0f}  ({res['elapsed']:.1f}s)")
    else:
        print(f"\n  ✗ ERROR: {res.get('error')}")
    return res["ok"]


def cmd_run_all(args=None):
    """Chain #9: Run all available days."""
    return cmd_baseline(args)


def cmd_ab_test(args=None):
    """Chain #12: A/B compare FinalTrader vs trader_ensemble."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #12: A/B Test")
    print("═══════════════════════════════════════════════════════")

    days = discover_days()
    if not days:
        print("[ERROR] No days!")
        return False

    # Use subset for speed
    test_days = days[:5] if len(days) > 5 else days

    # Trader A: FinalTrader
    print(f"\n--- Trader A: FinalTrader ---")
    a_pnls = []
    for r, d in test_days:
        res = run_single_day(r, d, ft.Trader)
        a_pnls.append(res["pnl"])

    # Trader B: trader_ensemble (if available)
    b_path = SCRIPT_DIR / "trader_ensemble.py"
    if b_path.exists():
        print(f"\n--- Trader B: trader_ensemble ---")
        import importlib.util
        spec = importlib.util.spec_from_file_location("trader_ensemble", str(b_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        trader_b_cls = mod.Trader

        b_pnls = []
        for r, d in test_days:
            res = run_single_day(r, d, trader_b_cls)
            b_pnls.append(res["pnl"])
    else:
        print(f"\n  trader_ensemble.py not found — comparing FinalTrader vs PlanB")
        pb_path = SCRIPT_DIR / "trader_planb.py"
        if pb_path.exists():
            spec = importlib.util.spec_from_file_location("trader_planb", str(pb_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            trader_b_cls = mod.Trader
            b_pnls = []
            for r, d in test_days:
                res = run_single_day(r, d, trader_b_cls)
                b_pnls.append(res["pnl"])
        else:
            b_pnls = [0] * len(test_days)

    # Compare
    print(f"\n{'='*60}")
    print(f"  Trader A total: {sum(a_pnls):,.0f}  mean: {np.mean(a_pnls):,.0f}")
    print(f"  Trader B total: {sum(b_pnls):,.0f}  mean: {np.mean(b_pnls):,.0f}")
    diff = sum(a_pnls) - sum(b_pnls)
    winner = "A (FinalTrader)" if diff > 0 else "B"
    print(f"  Winner: {winner}  (diff: {diff:+,.0f})")
    return True


def cmd_parallel(args=None):
    """Chain #59: Parallel backtest (sequential for now)."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #59: Parallel Backtest")
    print("═══════════════════════════════════════════════════════")
    # For now, just run baseline — real parallelism needs multiprocessing
    return cmd_baseline(args)


# ═══════════════════════════════════════════════════════════════════
# Strategy Library (Chains #13-#20)
# ═══════════════════════════════════════════════════════════════════

STRATEGIES_DIR = SCRIPT_DIR / "strategies"


def _run_strategy_on_days(trader_cls, days, name=""):
    """Run a trader class on given days and return results."""
    pnls = []
    for r, d in days:
        res = run_single_day(r, d, trader_cls)
        pnls.append(res["pnl"])
    total = sum(pnls)
    mean = np.mean(pnls) if pnls else 0
    print(f"  {name}: Total={total:,.0f}  Mean={mean:,.0f}  Days={len(pnls)}")
    return {"name": name, "total": total, "mean": float(mean), "pnls": pnls}


def cmd_strategy(args=None):
    """Chain #13/#14/#15: Run strategy by name."""
    name = "baseline"
    if args:
        for i, a in enumerate(args):
            if a == "--name" and i + 1 < len(args):
                name = args[i + 1]

    print(f"═══════════════════════════════════════════════════════")
    print(f" Strategy: {name}")
    print(f"═══════════════════════════════════════════════════════")

    days = discover_days()[:5]  # Quick test on 5 days

    if name == "baseline":
        return bool(_run_strategy_on_days(ft.Trader, days, "FinalTrader (baseline)"))
    elif name == "optimized":
        opt_path = SCRIPT_DIR / "trader_optimized.py"
        if opt_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("trader_optimized", str(opt_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return bool(_run_strategy_on_days(mod.Trader, days, "Optimized"))
        print("  trader_optimized.py not found — run training first")
        return False
    elif name == "ensemble":
        ens_path = SCRIPT_DIR / "trader_ensemble.py"
        if ens_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location("trader_ensemble", str(ens_path))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return bool(_run_strategy_on_days(mod.Trader, days, "Ensemble"))
        print("  trader_ensemble.py not found")
        return False
    else:
        # Load from strategies/
        strat_file = STRATEGIES_DIR / f"{name}.json"
        if strat_file.exists():
            params = json.loads(strat_file.read_text())
            print(f"  Loaded params from {strat_file}")
            # Would need to inject params and run — delegate to train
            return True
        print(f"  Strategy '{name}' not found")
        return False


def cmd_strategy_new(args=None):
    """Chain #16: Create new strategy from params."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #16: New Strategy from Params")
    print("═══════════════════════════════════════════════════════")

    params_file = SCRIPT_DIR / "data" / "trained" / "best_params.json"
    if params_file.exists():
        data = json.loads(params_file.read_text())
        params = data["params"]
        name = f"trained_{time.strftime('%Y%m%d_%H%M')}"
        out = STRATEGIES_DIR / f"{name}.json"
        STRATEGIES_DIR.mkdir(exist_ok=True)
        out.write_text(json.dumps({"name": name, "params": params,
                                    "pnl": data.get("pnl", 0),
                                    "timestamp": time.strftime("%Y-%m-%d %H:%M")}, indent=2))
        print(f"\n  ✓ Saved strategy: {out}")
        return True
    print("\n  No trained params found — run training first")
    return False


def cmd_strategy_save(args=None):
    """Chain #17: Save current strategy to library."""
    return cmd_strategy_new(args)


def cmd_strategy_load(args=None):
    """Chain #18: Load and test saved strategy."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #18: Load Saved Strategy")
    print("═══════════════════════════════════════════════════════")

    strats = list(STRATEGIES_DIR.glob("*.json")) if STRATEGIES_DIR.exists() else []
    if not strats:
        print("\n  No saved strategies")
        return False

    for s in strats:
        data = json.loads(s.read_text())
        print(f"  {s.stem}: PnL={data.get('pnl', '?')}")

    return True


def cmd_strategy_list(args=None):
    """Chain #19: List all strategies + PnL."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #19: Strategy Library")
    print("═══════════════════════════════════════════════════════")

    # Built-in strategies
    builtins = ["baseline (FinalTrader.py)", "optimized (trader_optimized.py)",
                "ensemble (trader_ensemble.py)", "planb (trader_planb.py)"]
    print("\n  Built-in:")
    for b in builtins:
        exists = "✓" if (SCRIPT_DIR / b.split("(")[1].rstrip(")")).exists() else "✗"
        print(f"    [{exists}] {b}")

    # Saved strategies
    strats = list(STRATEGIES_DIR.glob("*.json")) if STRATEGIES_DIR.exists() else []
    if strats:
        print(f"\n  Saved ({len(strats)}):")
        for s in strats:
            data = json.loads(s.read_text())
            print(f"    {s.stem}: PnL={data.get('pnl', '?')}  ({data.get('timestamp', '?')})")
    else:
        print(f"\n  No saved strategies yet")

    return True


def cmd_tournament(args=None):
    """Chain #20: Tournament — all strategies head to head."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #20: Strategy Tournament")
    print("═══════════════════════════════════════════════════════")

    days = discover_days()[:3]  # 3 days for speed
    if not days:
        print("[ERROR] No days!")
        return False

    results = []

    # FinalTrader baseline
    print(f"\n--- FinalTrader ---")
    r = _run_strategy_on_days(ft.Trader, days, "FinalTrader")
    results.append(r)

    # PlanB
    planb_path = SCRIPT_DIR / "trader_planb.py"
    if planb_path.exists():
        print(f"\n--- Plan B ---")
        import importlib.util
        spec = importlib.util.spec_from_file_location("planb", str(planb_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        r = _run_strategy_on_days(mod.Trader, days, "PlanB")
        results.append(r)

    # Ensemble
    ens_path = SCRIPT_DIR / "trader_ensemble.py"
    if ens_path.exists():
        print(f"\n--- Ensemble ---")
        spec = importlib.util.spec_from_file_location("ensemble", str(ens_path))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        r = _run_strategy_on_days(mod.Trader, days, "Ensemble")
        results.append(r)

    # Rank
    results.sort(key=lambda x: x["total"], reverse=True)
    print(f"\n{'='*60}")
    print(f"  TOURNAMENT RESULTS ({len(days)} days)")
    print(f"{'='*60}")
    for i, r in enumerate(results):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "  "
        print(f"  {medal} {r['name']:25s}  Total={r['total']:>8,.0f}  Mean={r['mean']:>8,.0f}")

    return True


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    extra_args = sys.argv[2:]

    commands = {
        "baseline": cmd_baseline,
        "smoke": cmd_smoke,
        "run-day": cmd_run_day,
        "run-all": cmd_run_all,
        "ab-test": cmd_ab_test,
        "parallel": cmd_parallel,
        "strategy": cmd_strategy,
        "strategy-new": cmd_strategy_new,
        "strategy-save": cmd_strategy_save,
        "strategy-load": cmd_strategy_load,
        "strategy-list": cmd_strategy_list,
        "tournament": cmd_tournament,
    }

    fn = commands.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)

    ok = fn(extra_args)
    sys.exit(0 if ok else 1)
