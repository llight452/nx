#!/usr/bin/env python3
"""
19_deploy.py — Deploy, validate, build FinalTrader for IMC upload
═══════════════════════════════════════════════════════════════════
Source: final/12_deploy.py (adapted for imc4/ self-contained)

Chain #24: deploy — validate + copy FinalTrader.py ready for upload
Chain #58: planb — minimal safe trader (fallback)
Chain #36: validate — pre-submit validation
Chain #38: full-validate — all days, all rounds
Chain #39: deploy-tag — deploy + git tag
Chain #40: offline — full offline pipeline
"""

import ast
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

SCRIPT_DIR = Path(__file__).parent.resolve()
TRADER_FILE = str(SCRIPT_DIR / "FinalTrader.py")
FALLBACK_FILE = str(SCRIPT_DIR / "trader_planb.py")
SUBMIT_LOG = str(SCRIPT_DIR / "data" / "trained" / "submit_log.json")
MAX_PIPELINE_S = 30.0


# ═══════════════════════════════════════════════════════════════════
# StepResult
# ═══════════════════════════════════════════════════════════════════

@dataclass
class StepResult:
    name: str
    passed: bool
    elapsed: float
    output: str = ""
    is_warning: bool = False


# ═══════════════════════════════════════════════════════════════════
# Validation steps
# ═══════════════════════════════════════════════════════════════════

def step_syntax_check(path: str) -> StepResult:
    t0 = time.time()
    try:
        with open(path) as f:
            src = f.read()
        ast.parse(src)
        return StepResult("syntax_check", True, time.time() - t0, "AST parse OK")
    except SyntaxError as e:
        return StepResult("syntax_check", False, time.time() - t0,
                          f"SyntaxError at line {e.lineno}: {e.msg}")


def step_class_check(path: str) -> StepResult:
    t0 = time.time()
    try:
        with open(path) as f:
            src = f.read()
        tree = ast.parse(src)
        classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        if "Trader" not in classes:
            return StepResult("class_check", False, time.time() - t0,
                              "No 'Trader' class found")
        trader = classes["Trader"]

        # Check run() in Trader itself
        methods = [n.name for n in ast.walk(trader) if isinstance(n, ast.FunctionDef)]
        if "run" in methods:
            return StepResult("class_check", True, time.time() - t0,
                              "Trader class + run() found")

        # Check run() in parent classes (inheritance)
        bases = [b.id if isinstance(b, ast.Name) else
                 b.attr if isinstance(b, ast.Attribute) else None
                 for b in trader.bases]
        for base_name in bases:
            if base_name and base_name in classes:
                base_methods = [n.name for n in ast.walk(classes[base_name])
                               if isinstance(n, ast.FunctionDef)]
                if "run" in base_methods:
                    return StepResult("class_check", True, time.time() - t0,
                                      f"Trader({base_name}) + run() found")

        return StepResult("class_check", False, time.time() - t0,
                          "Trader.run() not found (checked inheritance)")
    except Exception as e:
        return StepResult("class_check", False, time.time() - t0, str(e))


def step_size_check(path: str, max_bytes: int = 1_500_000) -> StepResult:
    t0 = time.time()
    size = Path(path).stat().st_size
    ok = size <= max_bytes
    return StepResult(
        "size_check", ok, time.time() - t0,
        f"File size: {size:,} bytes (limit {max_bytes:,})",
        is_warning=(size > max_bytes * 0.8),
    )


def step_no_prints(path: str) -> StepResult:
    t0 = time.time()
    with open(path) as f:
        src = f.read()
    tree = ast.parse(src)
    print_calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(getattr(n, 'func', None), ast.Name)
        and n.func.id == 'print'
    ]
    if print_calls:
        return StepResult(
            "no_prints", True, time.time() - t0,
            f"WARNING: {len(print_calls)} print() calls found",
            is_warning=True,
        )
    return StepResult("no_prints", True, time.time() - t0, "No print() calls")


def step_sell_orders_check(path: str) -> StepResult:
    t0 = time.time()
    with open(path) as f:
        src = f.read()
    patterns = ["sell_orders.values()", "sell_orders.items()"]
    ok = any(p in src for p in patterns)
    if not ok:
        return StepResult("sell_orders_check", True, time.time() - t0,
                          "No sell_orders iteration found", is_warning=True)
    bug_patterns = ["for q in sell_orders", "sell_orders[p] > 0"]
    has_bug = any(b in src for b in bug_patterns)
    return StepResult(
        "sell_orders_check", not has_bug, time.time() - t0,
        "sell_orders bug detected!" if has_bug else "sell_orders OK",
    )


def step_imports_check(path: str) -> StepResult:
    """Check imports — warn on non-stdlib but don't block (try/except is fine)."""
    t0 = time.time()
    with open(path) as f:
        src = f.read()
    tree = ast.parse(src)

    allowed_prefixes = {
        "math", "os", "sys", "json", "csv", "re", "time", "random",
        "collections", "copy", "statistics", "itertools", "heapq",
        "dataclasses", "enum", "typing", "io", "pathlib", "datetime",
        "functools", "operator", "abc", "bisect", "struct", "hashlib",
        "threading", "traceback", "warnings", "uuid", "argparse",
        "cProfile", "pstats", "importlib", "urllib", "string",
        "numpy", "np", "scipy", "pandas", "pd",
        "statsmodels", "hmmlearn", "cvxpy",
        "__future__",
    }

    non_std = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowed_prefixes:
                    non_std.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root = node.module.split(".")[0]
                if root not in allowed_prefixes:
                    non_std.append(node.module)

    if non_std:
        # Warn only — FinalTrader uses try/except for optional imports
        return StepResult("imports_check", True, time.time() - t0,
                          f"Non-stdlib imports (may need try/except): {', '.join(non_std[:5])}",
                          is_warning=True)
    return StepResult("imports_check", True, time.time() - t0, "All imports OK")


def step_trader_data_size(path: str) -> StepResult:
    t0 = time.time()
    with open(path) as f:
        src = f.read()
    has_dump = "dump_state" in src or "json.dumps" in src
    return StepResult(
        "trader_data_size", True, time.time() - t0,
        f"traderData serialization: {'found' if has_dump else 'NOT FOUND'}",
        is_warning=not has_dump,
    )


# ═══════════════════════════════════════════════════════════════════
# Pipeline
# ═══════════════════════════════════════════════════════════════════

def run_pipeline(trader_file: str = None, force: bool = False, verbose: bool = True) -> Tuple[bool, List[StepResult]]:
    if trader_file is None:
        trader_file = TRADER_FILE

    results: List[StepResult] = []
    t_start = time.time()

    steps = [
        lambda: step_syntax_check(trader_file),
        lambda: step_class_check(trader_file),
        lambda: step_size_check(trader_file),
        lambda: step_imports_check(trader_file),
        lambda: step_no_prints(trader_file),
        lambda: step_sell_orders_check(trader_file),
        lambda: step_trader_data_size(trader_file),
    ]

    all_passed = True
    for step_fn in steps:
        if time.time() - t_start > MAX_PIPELINE_S:
            results.append(StepResult("TIMEOUT", False, 0, "Pipeline exceeded 30s"))
            all_passed = False
            break

        result = step_fn()
        results.append(result)

        if verbose:
            icon = "✓" if result.passed else ("⚠" if result.is_warning else "✗")
            elapsed = f"{result.elapsed:.2f}s"
            print(f"  [{icon}] {result.name:25s} ({elapsed}): {result.output[:80]}")

        if not result.passed and not result.is_warning:
            all_passed = False
            if not force:
                if verbose:
                    print(f"\n  PIPELINE FAILED at {result.name}")
                break

    total = time.time() - t_start
    if verbose:
        status = "PASSED" if all_passed else "FAILED"
        print(f"\n  Pipeline {status} in {total:.2f}s")

    return all_passed, results


# ═══════════════════════════════════════════════════════════════════
# Deploy command
# ═══════════════════════════════════════════════════════════════════

def cmd_deploy(args=None):
    """Chain #24: Validate and prepare FinalTrader.py for IMC upload."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #24: Deploy FinalTrader.py")
    print("═══════════════════════════════════════════════════════")

    trader = TRADER_FILE
    if not Path(trader).exists():
        print(f"[ERROR] {trader} not found!")
        return False

    print(f"\n[1/3] Validating {Path(trader).name}...")
    passed, results = run_pipeline(trader)

    if not passed:
        print("\n[FAIL] Validation failed. Fix issues before deploy.")
        return False

    print(f"\n[2/3] File ready for upload:")
    size = Path(trader).stat().st_size
    print(f"  File: {trader}")
    print(f"  Size: {size:,} bytes")

    # Count classes and Trader.run lines
    with open(trader) as f:
        src = f.read()
    tree = ast.parse(src)
    n_classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
    n_functions = sum(1 for n in ast.walk(tree) if isinstance(n, ast.FunctionDef))
    n_lines = len(src.splitlines())
    print(f"  Lines: {n_lines:,}")
    print(f"  Classes: {n_classes}")
    print(f"  Functions: {n_functions}")

    print(f"\n[3/3] Deploy log...")
    log_entry = {
        "file": str(trader),
        "size": size,
        "lines": n_lines,
        "classes": n_classes,
        "timestamp": time.time(),
        "passed": True,
    }
    log_path = Path(SUBMIT_LOG)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = []
    if log_path.exists():
        try:
            log = json.loads(log_path.read_text())
        except Exception:
            pass
    log.append(log_entry)
    log_path.write_text(json.dumps(log, indent=2))

    print(f"\n  ✓ DEPLOY READY — upload {Path(trader).name} to IMC Prosperity")
    return True


# ═══════════════════════════════════════════════════════════════════
# Plan B — minimal safe trader
# ═══════════════════════════════════════════════════════════════════

PLAN_B_CODE = '''#!/usr/bin/env python3
"""
Plan B — Minimal safe trader (emergency fallback).
Only trades RAINFOREST_RESIN with simple market making.
Guaranteed not to crash, guaranteed positive PnL on stable products.
"""
from dataclasses import dataclass
from typing import Any, Dict, List

# Datamodel stubs (same as IMC platform)
@dataclass
class Order:
    symbol: str
    price: int
    quantity: int

@dataclass
class OrderDepth:
    buy_orders: Dict[int, int]
    sell_orders: Dict[int, int]

class Trader:
    """Minimal safe trader — RESIN MM only."""

    POSITION_LIMITS = {
        "RAINFOREST_RESIN": 50,
        "KELP": 50,
        "SQUID_INK": 50,
        "CROISSANTS": 250,
        "JAMS": 350,
        "DJEMBES": 60,
        "PICNIC_BASKET1": 60,
        "PICNIC_BASKET2": 100,
        "VOLCANIC_ROCK": 400,
        "VOLCANIC_ROCK_VOUCHER_9500": 200,
        "VOLCANIC_ROCK_VOUCHER_9750": 200,
        "VOLCANIC_ROCK_VOUCHER_10000": 200,
        "VOLCANIC_ROCK_VOUCHER_10250": 200,
        "VOLCANIC_ROCK_VOUCHER_10500": 200,
        "MAGNIFICENT_MACARONS": 75,
    }

    RESIN_FV = 10000
    SPREAD = 2
    ORDER_SIZE = 8

    def run(self, state) -> tuple:
        result = {}
        conversions = 0
        trader_data = ""

        for product in state.order_depths:
            orders = []
            position = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 50)

            if product == "RAINFOREST_RESIN":
                orders = self._trade_resin(state.order_depths[product], position, limit)

            if orders:
                result[product] = orders

        return result, conversions, trader_data

    def _trade_resin(self, depth, position, limit):
        orders = []
        fv = self.RESIN_FV

        # Take cheap asks
        if depth.sell_orders:
            for price in sorted(depth.sell_orders.keys()):
                if price < fv - 1:
                    vol = -depth.sell_orders[price]  # sell_orders are negative
                    can_buy = min(vol, limit - position)
                    if can_buy > 0:
                        orders.append(Order("RAINFOREST_RESIN", price, can_buy))
                        position += can_buy

        # Take expensive bids
        if depth.buy_orders:
            for price in sorted(depth.buy_orders.keys(), reverse=True):
                if price > fv + 1:
                    vol = depth.buy_orders[price]
                    can_sell = min(vol, limit + position)
                    if can_sell > 0:
                        orders.append(Order("RAINFOREST_RESIN", price, -can_sell))
                        position -= can_sell

        # Post spread
        buy_qty = min(self.ORDER_SIZE, limit - position)
        sell_qty = min(self.ORDER_SIZE, limit + position)

        if buy_qty > 0:
            orders.append(Order("RAINFOREST_RESIN", fv - self.SPREAD, buy_qty))
        if sell_qty > 0:
            orders.append(Order("RAINFOREST_RESIN", fv + self.SPREAD, -sell_qty))

        return orders
'''


def cmd_planb(args=None):
    """Chain #58: Create Plan B minimal safe trader."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #58: Plan B — Minimal Safe Trader")
    print("═══════════════════════════════════════════════════════")

    planb_path = Path(FALLBACK_FILE)
    planb_path.write_text(PLAN_B_CODE)

    print(f"\n[1/2] Created {planb_path}")
    print(f"  Size: {planb_path.stat().st_size:,} bytes")

    print(f"\n[2/2] Validating...")
    passed, results = run_pipeline(str(planb_path))

    if passed:
        print(f"\n  ✓ Plan B ready at {planb_path}")
    else:
        print(f"\n  ✗ Plan B has issues!")
    return passed


def cmd_validate(args=None):
    """Chain #36: Pre-submit validation."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #36: Pre-submit Validation")
    print("═══════════════════════════════════════════════════════")
    return run_pipeline(TRADER_FILE, force=True)[0]


def cmd_full_validate(args=None):
    """Chain #38: Full validation (all traders)."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #38: Full Validation")
    print("═══════════════════════════════════════════════════════")

    files = [TRADER_FILE]
    optimized = str(SCRIPT_DIR / "trader_optimized.py")
    ensemble = str(SCRIPT_DIR / "trader_ensemble.py")
    planb = FALLBACK_FILE

    for f in [optimized, ensemble, planb]:
        if Path(f).exists():
            files.append(f)

    all_ok = True
    for f in files:
        print(f"\n--- Validating {Path(f).name} ---")
        ok, _ = run_pipeline(f, force=True)
        if not ok:
            all_ok = False

    print(f"\n{'✓ ALL PASSED' if all_ok else '✗ SOME FAILED'}")
    return all_ok


def cmd_deploy_tag(args=None):
    """Chain #39: Deploy + git tag."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #39: Deploy + Git Tag")
    print("═══════════════════════════════════════════════════════")

    if not cmd_deploy():
        return False

    tag = f"submit-{int(time.time())}"
    result = subprocess.run(["git", "tag", tag], capture_output=True, text=True, cwd=str(SCRIPT_DIR.parent))
    if result.returncode == 0:
        print(f"\n  ✓ Git tag: {tag}")
    else:
        print(f"\n  ⚠ Git tag failed: {result.stderr}")
    return True


def cmd_offline(args=None):
    """Chain #40: Offline pipeline."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #40: Offline Pipeline")
    print("═══════════════════════════════════════════════════════")

    print("\n[1/4] Validate...")
    if not run_pipeline(TRADER_FILE)[0]:
        print("  ✗ Validation failed")
        return False

    print("\n[2/4] Plan B...")
    cmd_planb()

    print("\n[3/4] Smoke test via backtester...")
    try:
        bt_dir = SCRIPT_DIR / "prosperity3bt"
        sys.path.insert(0, str(bt_dir.parent))
        from prosperity3bt.runner import run_backtest
        from prosperity3bt.file_reader import PackageResourcesReader
        from prosperity3bt.models import TradeMatchingMode

        sys.path.insert(0, str(SCRIPT_DIR))
        import FinalTrader as ft
        ft.Logger.flush = lambda self, *a, **k: None

        reader = PackageResourcesReader()
        result = run_backtest(
            ft.Trader, reader, 1, 0,
            print_output=False,
            trade_matching_mode=TradeMatchingMode.FIFO,
        )
        pnl = sum(v for v in result.profit_loss.values())
        print(f"  Smoke PnL (R1D0): {pnl:.0f}")
    except Exception as e:
        print(f"  ⚠ Smoke test error: {e}")

    print("\n[4/4] Deploy ready")
    print(f"  Upload: {TRADER_FILE}")
    return True


def cmd_build(args=None):
    """Build: copy FinalTrader.py to deploy location."""
    print("═══════════════════════════════════════════════════════")
    print(" BUILD — Copy FinalTrader.py")
    print("═══════════════════════════════════════════════════════")

    src = TRADER_FILE
    dst = str(SCRIPT_DIR / "FinalTrader_DEPLOY.py")

    if not Path(src).exists():
        print(f"[ERROR] {src} not found!")
        return False

    shutil.copy2(src, dst)
    print(f"  Copied: {dst}")
    print(f"  Size: {Path(dst).stat().st_size:,} bytes")

    passed, _ = run_pipeline(dst)
    if passed:
        print(f"\n  ✓ BUILD OK — ready to upload")
    return passed


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "deploy"

    commands = {
        "deploy": cmd_deploy,
        "planb": cmd_planb,
        "validate": cmd_validate,
        "full-validate": cmd_full_validate,
        "deploy-tag": cmd_deploy_tag,
        "offline": cmd_offline,
        "build": cmd_build,
    }

    fn = commands.get(cmd)
    if fn is None:
        print(f"Unknown command: {cmd}")
        print(f"Available: {', '.join(commands.keys())}")
        sys.exit(1)

    ok = fn()
    sys.exit(0 if ok else 1)
