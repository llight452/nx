#!/usr/bin/env python3
"""
15_train.py — Optuna training pipeline for imc4/
═══════════════════════════════════════════════════
Source: final/train.py (adapted for imc4/ self-contained)

Chain #1:  --samples 10    — Train quick (10 trials)
Chain #2:  --samples 100   — Train fast
Chain #3:  --samples 500   — Train medium
Chain #4:  --samples 2000  — Train full
Chain #5:  --resume         — Resume interrupted
Chain #6:  --deploy         — Deploy best → trader_optimized.py
Chain #23: --retrain        — Re-train on new data
"""

import argparse
import copy
import json
import math
import os
import pickle
import random
import re
import sys
import time
import traceback
from collections import defaultdict
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
# Import FinalTrader + patch
# ═══════════════════════════════════════════════════════════════════
import FinalTrader as ft

ft.Logger.flush = lambda self, *a, **k: None
if hasattr(ft, 'Logger_full'):
    ft.Logger_full.flush = lambda self, *a, **k: None

ft.logger.log = lambda *a, **k: None
ft.logger.print = lambda *a, **k: None

if hasattr(ft, 'timeout_guard'):
    ft.timeout_guard.start = lambda: None
    ft.timeout_guard.check = lambda: None

ft.CONFIG["PROFILE_EVERY"] = 999999

# ═══════════════════════════════════════════════════════════════════
# Paths
# ═══════════════════════════════════════════════════════════════════
TRAINED_DIR = SCRIPT_DIR / "data" / "trained"
BEST_PARAMS_FILE = TRAINED_DIR / "best_params.json"

# ═══════════════════════════════════════════════════════════════════
# Save original constants
# ═══════════════════════════════════════════════════════════════════
_ORIG_CONFIG = copy.deepcopy(ft.CONFIG)
_ORIG_EMA_ALPHA = copy.deepcopy(ft.EMA_ALPHA)
_ORIG_SCALARS = {}
for _n in ["KF_Q", "KF_R", "MW_ETA", "MW_LOSS_CLIP", "CB_LOSS_LIMIT",
           "CB_RESET_TICKS", "ADV_THRESHOLD", "ROLLING_WINDOW",
           "MIN_SPREAD", "STABLE_SOFT_LIMIT_FRAC", "STABLE_SPREAD_MIN",
           "STABLE_SPREAD_MAX", "STABLE_SKEW_THRESHOLD",
           "VOLATILE_SOFT_LIMIT_FRAC", "VOLATILE_SPREAD_MIN", "VOLATILE_SPREAD_MAX",
           "EMA_ALPHA_FAST", "EMA_ALPHA_SLOW",
           "AS_GAMMA_DEFAULT", "AS_VOL_LOOKBACK",
           "KALMAN_Q_DEFAULT", "KALMAN_R_DEFAULT",
           "OFI_LOOKBACK", "OFI_BETA_DEFAULT", "OFI_CAP",
           "ADV_SEL_LOOKBACK", "ADV_SEL_THRESHOLD",
           "QUOTE_REFRESH_TICKS"]:
    if hasattr(ft, _n):
        _ORIG_SCALARS[_n] = getattr(ft, _n)


# ═══════════════════════════════════════════════════════════════════
# Day discovery
# ═══════════════════════════════════════════════════════════════════
def discover_days() -> List[Tuple[int, int]]:
    days = set()
    # 1. P3 built-in data (prosperity3bt/resources/)
    reader = PackageResourcesReader()
    for r in range(0, 10):
        for d in range(-5, 15):
            try:
                if has_day_data(reader, r, d):
                    days.add((r, d))
            except Exception:
                pass
    # 2. P4 external data (data/p4_rounds/)
    p4_dir = SCRIPT_DIR / "data" / "p4_rounds"
    if p4_dir.exists():
        from prosperity3bt.file_reader import FileSystemReader
        for rdir in sorted(p4_dir.iterdir()):
            if rdir.is_dir() and rdir.name.startswith("round"):
                try:
                    rnum = int(rdir.name.replace("round", ""))
                except ValueError:
                    continue
                p4_reader = FileSystemReader(p4_dir)
                for d in range(-5, 15):
                    try:
                        if has_day_data(p4_reader, rnum, d):
                            days.add((rnum + 100, d))  # offset 100 to avoid P3 collision
                    except Exception:
                        pass
        if any(r >= 100 for r, _ in days):
            p4_count = sum(1 for r, _ in days if r >= 100)
            print(f"  [P4] Found {p4_count} P4 days in {p4_dir}", flush=True)
    return sorted(days)


# ═══════════════════════════════════════════════════════════════════
# Parameter Space (55 params in 6 groups)
# ═══════════════════════════════════════════════════════════════════
PARAM_DEFS = {
    "RESIN": [
        ("resin_spread",                "int",   1,    6,    4),
        ("resin_order_size",            "int",   3,    25,   10),
        ("resin_skew_factor",           "float", 0.0,  2.0,  0.5),
        ("resin_ema_alpha",             "float", 0.05, 0.3,  0.1),
        ("resin_soft_frac",             "float", 0.6,  0.95, 0.80),
        ("resin_aggression_ticks",      "int",   1,    5,    1),
        ("resin_liquidation_threshold", "int",   20,   45,   35),
        ("stable_spread_min",           "int",   1,    3,    1),
        ("stable_spread_max",           "int",   1,    5,    2),
        ("stable_skew_threshold",       "int",   20,   45,   35),
    ],
    "VOLATILE": [
        ("kelp_ema_alpha",             "float", 0.05, 0.7,  0.3),
        ("squid_ema_alpha",            "float", 0.05, 0.7,  0.3),
        ("ema_alpha_fast",             "float", 0.15, 0.6,  0.35),
        ("ema_alpha_slow",             "float", 0.02, 0.15, 0.07),
        ("as_gamma",                   "float", 0.01, 0.15, 0.05),
        ("as_gamma_kelp",              "float", 0.01, 0.15, 0.05),
        ("volatile_spread_min",        "int",   1,    6,    3),
        ("volatile_spread_max",        "int",   2,    8,    4),
        ("spike_sigma",                "float", 2.0,  5.0,  3.0),
        ("spike_window",               "int",   5,    20,   10),
        ("spike_recovery_ticks",       "int",   20,   100,  50),
        ("kelp_spike_spread_mult",     "float", 1.0,  4.0,  2.0),
        ("squid_spike_spread_mult",    "float", 1.5,  5.0,  2.5),
        ("squid_spike_size_mult",      "float", 0.1,  0.5,  0.25),
        ("ofi_beta",                   "float", 0.001, 0.05, 0.01),
    ],
    "BASKET": [
        ("zscore_enter",               "float", 1.0,  4.0,  2.0),
        ("zscore_exit",                "float", 0.1,  1.5,  0.5),
        ("basket_rolling_window",      "int",   100,  1000, 500),
        ("hedge_recalc_ticks",         "int",   50,   300,  100),
        ("pb1_zscore_enter",           "float", 1.0,  4.0,  2.0),
        ("pb1_zscore_exit",            "float", 0.1,  1.5,  0.5),
        ("pb2_zscore_enter",           "float", 1.0,  4.0,  2.0),
        ("pb2_zscore_exit",            "float", 0.1,  1.5,  0.5),
    ],
    "OPTIONS": [
        ("delta_band",                 "int",   2,    10,   5),
        ("iv_sell_threshold",          "float", 0.5,  5.0,  2.0),
        ("iv_buy_threshold",           "float", 0.5,  5.0,  2.0),
        ("min_edge_iv",                "float", 0.5,  5.0,  2.0),
        ("vega_limit_pct",             "float", 0.1,  0.5,  0.30),
    ],
    "MACARONS": [
        ("macarons_recalc_ticks",      "int",   100,  1000, 500),
        ("macarons_conversion_block",  "int",   1,    15,   7),
    ],
    "GLOBAL": [
        ("kf_Q",                       "float", 1e-5, 0.1,  1e-4,  True),
        ("kf_R",                       "float", 1e-3, 1.0,  1e-2,  True),
        ("mw_eta",                     "float", 0.001, 0.1, 0.01,  True),
        ("mw_loss_clip",               "float", 0.5,  5.0,  2.0),
        ("cb_loss_limit",              "float", -1000, -50, -500),
        ("cb_reset_ticks",             "int",   50,   500,  200),
        ("adv_threshold",              "float", 0.5,  0.9,  0.70),
        ("rolling_window",             "int",   100,  500,  300),
        ("warmup_ticks",               "int",   5,    50,   20),
        ("phase_small_end",            "int",   50,   200,  100),
        ("phase_half_end",             "int",   100,  400,  200),
        ("phase_reduce_start",         "int",   600,  900,  800),
        ("phase_exit_start",           "int",   900,  990,  950),
        ("liquidation_tick",           "int",   7000, 9000, 8000),
        ("close_tick",                 "int",   9500, 9900, 9800),
        ("kill_pnl_threshold",         "float", -1000, -100, -500),
        ("kill_drawdown_threshold",    "float", -800, -100, -300),
    ],
}

_TOTAL_PARAMS = sum(len(v) for v in PARAM_DEFS.values())


def suggest_params(trial, group: str = "ALL") -> Dict[str, Any]:
    p = {}
    groups = [group] if group != "ALL" else list(PARAM_DEFS.keys())
    for g in groups:
        for pdef in PARAM_DEFS.get(g, []):
            name, ptype = pdef[0], pdef[1]
            lo, hi = pdef[2], pdef[3]
            log = len(pdef) > 5 and pdef[5]
            if ptype == "int":
                p[name] = trial.suggest_int(name, lo, hi)
            elif ptype == "float":
                p[name] = trial.suggest_float(name, lo, hi, log=log)
    return p


def get_defaults(group: str = "ALL") -> Dict[str, Any]:
    p = {}
    groups = [group] if group != "ALL" else list(PARAM_DEFS.keys())
    for g in groups:
        for pdef in PARAM_DEFS.get(g, []):
            p[pdef[0]] = pdef[4]
    return p


# ═══════════════════════════════════════════════════════════════════
# Parameter injection
# ═══════════════════════════════════════════════════════════════════
def _set(module, name, value):
    if hasattr(module, name):
        setattr(module, name, value)


def inject_params(params: Dict[str, Any]) -> None:
    ft.CONFIG["RAINFOREST_RESIN"]["spread"] = params.get("resin_spread", 4)
    ft.CONFIG["RAINFOREST_RESIN"]["order_size"] = params.get("resin_order_size", 10)
    ft.CONFIG["RAINFOREST_RESIN"]["skew_factor"] = params.get("resin_skew_factor", 0.5)
    ft.CONFIG["RAINFOREST_RESIN"]["ema_alpha"] = params.get("resin_ema_alpha", 0.1)
    ft.CONFIG["WARMUP_TICKS"] = params.get("warmup_ticks", 20)
    ft.CONFIG["PHASE_SMALL_END"] = params.get("phase_small_end", 100)
    ft.CONFIG["PHASE_HALF_END"] = params.get("phase_half_end", 200)
    ft.CONFIG["PHASE_REDUCE_START"] = params.get("phase_reduce_start", 800)
    ft.CONFIG["PHASE_EXIT_START"] = params.get("phase_exit_start", 950)
    ft.CONFIG["LIQUIDATION_TICK"] = params.get("liquidation_tick", 8000)
    ft.CONFIG["CLOSE_TICK"] = params.get("close_tick", 9800)

    ft.EMA_ALPHA["KELP"] = params.get("kelp_ema_alpha", 0.3)
    ft.EMA_ALPHA["SQUID_INK"] = params.get("squid_ema_alpha", 0.3)
    ft.EMA_ALPHA["RAINFOREST_RESIN"] = params.get("resin_ema_alpha", 0.1)
    ft.KF_Q = params.get("kf_Q", 1e-4)
    ft.KF_R = params.get("kf_R", 1e-2)
    ft.MW_ETA = params.get("mw_eta", 0.01)
    ft.MW_LOSS_CLIP = params.get("mw_loss_clip", 2.0)
    ft.CB_LOSS_LIMIT = params.get("cb_loss_limit", -500)
    ft.CB_RESET_TICKS = params.get("cb_reset_ticks", 200)
    ft.ADV_THRESHOLD = params.get("adv_threshold", 0.70)
    ft.ROLLING_WINDOW = params.get("rolling_window", 300)

    _set(ft, "STABLE_SPREAD_MIN", params.get("stable_spread_min", 1))
    _set(ft, "STABLE_SPREAD_MAX", params.get("stable_spread_max", 2))
    _set(ft, "STABLE_SKEW_THRESHOLD", params.get("stable_skew_threshold", 35))
    _set(ft, "STABLE_SOFT_LIMIT_FRAC", params.get("resin_soft_frac", 0.80))
    _set(ft, "VOLATILE_SPREAD_MIN", params.get("volatile_spread_min", 3))
    _set(ft, "VOLATILE_SPREAD_MAX", params.get("volatile_spread_max", 4))
    _set(ft, "EMA_ALPHA_FAST", params.get("ema_alpha_fast", 0.35))
    _set(ft, "EMA_ALPHA_SLOW", params.get("ema_alpha_slow", 0.07))
    _set(ft, "AS_GAMMA_DEFAULT", params.get("as_gamma", 0.05))
    _set(ft, "AS_VOL_LOOKBACK", 100)
    _set(ft, "KALMAN_Q_DEFAULT", params.get("kf_Q", 1e-4))
    _set(ft, "KALMAN_R_DEFAULT", params.get("kf_R", 1e-2))
    _set(ft, "OFI_BETA_DEFAULT", params.get("ofi_beta", 0.01))
    _set(ft, "ADV_SEL_THRESHOLD", params.get("adv_threshold", 0.70))

    ft.Trader.AS_GAMMA = params.get("as_gamma", 0.05)
    ft.Trader.AS_GAMMA_KELP = params.get("as_gamma_kelp", 0.05)
    ft.Trader.SPIKE_SIGMA = params.get("spike_sigma", 3.0)
    ft.Trader.SPIKE_WINDOW = params.get("spike_window", 10)
    ft.Trader.SPIKE_RECOVERY_TICKS = params.get("spike_recovery_ticks", 50)
    ft.Trader.KELP_FLASH_SPIKE_SPREAD_MULT = params.get("kelp_spike_spread_mult", 2.0)
    ft.Trader.SQUID_SPIKE_SPREAD_MULT = params.get("squid_spike_spread_mult", 2.5)
    ft.Trader.SQUID_SPIKE_SIZE_MULT = params.get("squid_spike_size_mult", 0.25)
    ft.Trader.RESIN_AGGRESSION_TICKS = params.get("resin_aggression_ticks", 1)
    ft.Trader.RESIN_LIQUIDATION_THRESHOLD = params.get("resin_liquidation_threshold", 35)
    ft.Trader.ZSCORE_ENTER = params.get("zscore_enter", 2.0)
    ft.Trader.ZSCORE_EXIT = params.get("zscore_exit", 0.5)
    ft.Trader.ROLLING_WINDOW = params.get("basket_rolling_window", 500)
    ft.Trader.HEDGE_RECALC_TICKS = params.get("hedge_recalc_ticks", 100)
    ft.Trader.PB1_ZSCORE_ENTER = params.get("pb1_zscore_enter", 2.0)
    ft.Trader.PB1_ZSCORE_EXIT = params.get("pb1_zscore_exit", 0.5)
    ft.Trader.PB2_ZSCORE_ENTER = params.get("pb2_zscore_enter", 2.0)
    ft.Trader.PB2_ZSCORE_EXIT = params.get("pb2_zscore_exit", 0.5)
    ft.Trader.DELTA_BAND = params.get("delta_band", 5)
    ft.Trader.IV_SELL_THRESHOLD = params.get("iv_sell_threshold", 2.0)
    ft.Trader.IV_BUY_THRESHOLD = params.get("iv_buy_threshold", 2.0)
    ft.Trader.MIN_EDGE_IV = params.get("min_edge_iv", 2.0)
    ft.Trader.VEGA_LIMIT_PCT = params.get("vega_limit_pct", 0.30)
    ft.Trader.MACARONS_RECALC_TICKS = params.get("macarons_recalc_ticks", 500)
    ft.Trader.MACARONS_CONVERSION_BLOCK = params.get("macarons_conversion_block", 7)

    if "resin_soft_frac" in params:
        ft.Trader.SOFT_LIMIT_PCT["RAINFOREST_RESIN"] = params["resin_soft_frac"]

    ft.KillSwitch.PNL_THRESHOLD = params.get("kill_pnl_threshold", -500)
    ft.KillSwitch.DRAWDOWN_THRESHOLD = params.get("kill_drawdown_threshold", -300)


# ═══════════════════════════════════════════════════════════════════
# PnL extraction
# ═══════════════════════════════════════════════════════════════════
def extract_pnl(result) -> float:
    if not result.activity_logs:
        return 0.0
    last_ts = max(log.columns[1] for log in result.activity_logs)
    return sum(
        float(log.columns[16])
        for log in result.activity_logs
        if log.columns[1] == last_ts
    )


# ═══════════════════════════════════════════════════════════════════
# Runners
# ═══════════════════════════════════════════════════════════════════
def _get_reader(round_num: int):
    """Return appropriate reader: FileSystemReader for P4 data (round>=100), PackageResourcesReader for P3."""
    if round_num >= 100:
        from prosperity3bt.file_reader import FileSystemReader
        return FileSystemReader(SCRIPT_DIR / "data" / "p4_rounds"), round_num - 100
    return PackageResourcesReader(), round_num


def run_single_day(params: Dict, round_num: int, day_num: int) -> float:
    inject_params(params)
    trader = ft.Trader()
    try:
        reader, actual_round = _get_reader(round_num)
        result = run_backtest(
            trader, reader,
            round_num=actual_round, day_num=day_num,
            print_output=False,
            trade_matching_mode=TradeMatchingMode.worse,
            no_names=False, show_progress_bar=False,
        )
        return extract_pnl(result)
    except Exception as e:
        print(f"  [ERROR] R{round_num}D{day_num}: {e}", flush=True)
        return 0.0


def run_multi_day(params: Dict, days: List[Tuple[int, int]], max_days: int = 8) -> float:
    if len(days) > max_days:
        sample = random.sample(days, max_days)
    else:
        sample = list(days)
    pnls = [run_single_day(params, r, d) for r, d in sample]
    return float(np.mean(pnls)) if pnls else 0.0


# ═══════════════════════════════════════════════════════════════════
# Optuna phases (same as final/train.py)
# ═══════════════════════════════════════════════════════════════════
def run_optuna_phase1(n_trials, days, max_days=8):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    print(f"\n{'='*60}", flush=True)
    print(f"[PHASE 1] Optuna TPE — {n_trials} trials, {_TOTAL_PARAMS} params", flush=True)
    print(f"{'='*60}", flush=True)

    # Persistent storage — all trainings accumulate, no duplicates
    db_path = TRAINED_DIR / "optuna_study.db"
    TRAINED_DIR.mkdir(parents=True, exist_ok=True)
    storage = f"sqlite:///{db_path}"
    study = optuna.create_study(
        study_name="imc4_main",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(),
        storage=storage,
        load_if_exists=True,
    )
    prev_trials = len(study.trials)
    if prev_trials > 0:
        print(f"  [RESUME] {prev_trials} previous trials loaded, best={study.best_value:,.0f}", flush=True)

    best_so_far = float("-inf")
    t0 = time.time()

    def objective(trial):
        nonlocal best_so_far
        params = suggest_params(trial, "ALL")
        pnl = run_multi_day(params, days, max_days)
        if pnl > best_so_far:
            best_so_far = pnl
            print(f"  [NEW BEST] Trial {trial.number}: PnL={pnl:,.0f}  "
                  f"({(time.time()-t0)/60:.1f}m)", flush=True)
        return pnl

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    best_params = get_defaults()
    best_params.update(study.best_params)
    print(f"\n[PHASE 1] Best PnL: {study.best_value:,.0f}", flush=True)
    return best_params, study.best_value


def run_decomposed_phase2(base_params, n_trials_per_group, days, max_days=8):
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)

    groups = list(PARAM_DEFS.keys())
    print(f"\n{'='*60}", flush=True)
    print(f"[PHASE 2] Decomposed — {n_trials_per_group} trials × {len(groups)} groups", flush=True)
    print(f"{'='*60}", flush=True)

    current_best = dict(base_params)
    for group in groups:
        print(f"\n  [{group}] {len(PARAM_DEFS[group])} params...", flush=True)
        t0 = time.time()

        study = optuna.create_study(
            direction="maximize",
            sampler=optuna.samplers.TPESampler(seed=42),
        )

        def make_objective(grp, base):
            def objective(trial):
                params = dict(base)
                params.update(suggest_params(trial, grp))
                return run_multi_day(params, days, max_days)
            return objective

        study.optimize(make_objective(group, current_best),
                       n_trials=n_trials_per_group, show_progress_bar=False)
        for k, v in study.best_params.items():
            current_best[k] = v
        print(f"  [{group}] Best={study.best_value:,.0f}  ({(time.time()-t0)/60:.1f}m)", flush=True)

    combined_pnl = run_multi_day(current_best, days, max_days)
    print(f"\n[PHASE 2] Combined PnL: {combined_pnl:,.0f}", flush=True)
    return current_best, combined_pnl


def local_refinement_phase3(base_params, n_steps, days, max_days=8):
    print(f"\n{'='*60}", flush=True)
    print(f"[PHASE 3] Local refinement — {n_steps} steps", flush=True)
    print(f"{'='*60}", flush=True)

    best_params = dict(base_params)
    best_pnl = run_multi_day(best_params, days, max_days)

    all_defs = []
    for group_defs in PARAM_DEFS.values():
        all_defs.extend(group_defs)

    improved = 0
    for step in range(n_steps):
        pdef = random.choice(all_defs)
        name, ptype = pdef[0], pdef[1]
        lo, hi, default = pdef[2], pdef[3], pdef[4]

        candidate = dict(best_params)
        current_val = candidate.get(name, default)

        if ptype == "int":
            delta = max(1, int((hi - lo) * 0.1))
            new_val = max(lo, min(hi, current_val + random.randint(-delta, delta)))
        else:
            scale = (hi - lo) * 0.05
            new_val = max(lo, min(hi, current_val + random.gauss(0, scale)))

        candidate[name] = new_val
        pnl = run_multi_day(candidate, days, max_days)

        if pnl > best_pnl:
            best_pnl = pnl
            best_params = candidate
            improved += 1
            print(f"  Step {step+1}/{n_steps}: {name}={new_val:.4g} → PnL={pnl:,.0f} ✓", flush=True)

    print(f"\n[PHASE 3] Final PnL: {best_pnl:,.0f}  ({improved} improvements)", flush=True)
    return best_params, best_pnl


def walk_forward_validate(params, days, n_folds=3):
    print(f"\n{'='*60}", flush=True)
    print(f"[PHASE 4] Walk-forward — {n_folds} folds on {len(days)} days", flush=True)
    print(f"{'='*60}", flush=True)

    sorted_days = sorted(days)

    # Special case: 1 fold = just run all days as test (no train/test split)
    if n_folds <= 1:
        test_pnl = run_multi_day(params, sorted_days, len(sorted_days))
        print(f"  All-days PnL: {test_pnl:,.0f}", flush=True)
        return {"mean_train": test_pnl, "mean_test": test_pnl, "overfit_pct": 0.0}

    fold_size = max(1, len(sorted_days) // n_folds)

    train_pnls, test_pnls = [], []
    for fold in range(n_folds):
        test_start = fold * fold_size
        test_end = min(test_start + fold_size, len(sorted_days))
        test_days = sorted_days[test_start:test_end]
        train_days = sorted_days[:test_start] + sorted_days[test_end:]
        if not test_days or not train_days:
            continue

        train_pnl = run_multi_day(params, train_days, len(train_days))
        test_pnl = run_multi_day(params, test_days, len(test_days))
        train_pnls.append(train_pnl)
        test_pnls.append(test_pnl)
        print(f"  Fold {fold+1}: Train={train_pnl:,.0f}  Test={test_pnl:,.0f}", flush=True)

    mean_train = float(np.mean(train_pnls)) if train_pnls else 0
    mean_test = float(np.mean(test_pnls)) if test_pnls else 0
    overfit = (mean_train - mean_test) / max(abs(mean_train), 1) * 100

    print(f"\n[PHASE 4] Train={mean_train:,.0f}  Test={mean_test:,.0f}  Overfit={overfit:+.1f}%", flush=True)
    return {"mean_train": mean_train, "mean_test": mean_test, "overfit_pct": overfit}


# ═══════════════════════════════════════════════════════════════════
# Deploy — generate trader_optimized.py
# ═══════════════════════════════════════════════════════════════════
def generate_trader_optimized(params, pnl_info=""):
    src_path = SCRIPT_DIR / "FinalTrader.py"
    dst_path = SCRIPT_DIR / "FinalTrader.py"  # OVERWRITE main trader (was trader_optimized.py)
    backup_path = SCRIPT_DIR / "trader_optimized.py"  # backup copy
    source = src_path.read_text(encoding="utf-8")
    # Strip previous optimized params block if exists
    marker = "# " + "=" * 70 + "\n# OPTIMIZED PARAMETERS"
    if marker in source:
        source = source[:source.index(marker)]

    lines = ["", "# " + "=" * 70,
             "# OPTIMIZED PARAMETERS",
             f"# Generated by 15_train.py on {time.strftime('%Y-%m-%d %H:%M')}",
             f"# {pnl_info}" if pnl_info else "",
             "# " + "=" * 70, ""]

    _cfg_map = {
        "resin_spread": ('CONFIG["RAINFOREST_RESIN"]["spread"]', int),
        "resin_order_size": ('CONFIG["RAINFOREST_RESIN"]["order_size"]', int),
        "resin_skew_factor": ('CONFIG["RAINFOREST_RESIN"]["skew_factor"]', float),
        "resin_ema_alpha": ('CONFIG["RAINFOREST_RESIN"]["ema_alpha"]', float),
        "warmup_ticks": ('CONFIG["WARMUP_TICKS"]', int),
        "phase_small_end": ('CONFIG["PHASE_SMALL_END"]', int),
        "phase_half_end": ('CONFIG["PHASE_HALF_END"]', int),
        "phase_reduce_start": ('CONFIG["PHASE_REDUCE_START"]', int),
        "phase_exit_start": ('CONFIG["PHASE_EXIT_START"]', int),
        "liquidation_tick": ('CONFIG["LIQUIDATION_TICK"]', int),
        "close_tick": ('CONFIG["CLOSE_TICK"]', int),
    }
    for pname, (target, typ) in _cfg_map.items():
        if pname in params:
            lines.append(f"{target} = {typ(params[pname])!r}")

    _scalar_map = {
        "kelp_ema_alpha": ('EMA_ALPHA["KELP"]', float),
        "squid_ema_alpha": ('EMA_ALPHA["SQUID_INK"]', float),
        "kf_Q": ("KF_Q", float), "kf_R": ("KF_R", float),
        "mw_eta": ("MW_ETA", float), "mw_loss_clip": ("MW_LOSS_CLIP", float),
        # "cb_loss_limit": ("CB_LOSS_LIMIT", float),  # НЕ переписываем — уже -500000
        "cb_reset_ticks": ("CB_RESET_TICKS", int),
        "rolling_window": ("ROLLING_WINDOW", int),
        "stable_spread_min": ("STABLE_SPREAD_MIN", int),
        "stable_spread_max": ("STABLE_SPREAD_MAX", int),
        "volatile_spread_min": ("VOLATILE_SPREAD_MIN", int),
        "volatile_spread_max": ("VOLATILE_SPREAD_MAX", int),
        "ema_alpha_fast": ("EMA_ALPHA_FAST", float),
        "ema_alpha_slow": ("EMA_ALPHA_SLOW", float),
        "as_gamma": ("AS_GAMMA_DEFAULT", float),
        "ofi_beta": ("OFI_BETA_DEFAULT", float),
    }
    lines.append("")
    for pname, (target, typ) in _scalar_map.items():
        if pname in params:
            lines.append(f"{target} = {typ(params[pname])!r}")

    _class_map = {
        "as_gamma": ("Trader.AS_GAMMA", float),
        "as_gamma_kelp": ("Trader.AS_GAMMA_KELP", float),
        "spike_sigma": ("Trader.SPIKE_SIGMA", float),
        "spike_window": ("Trader.SPIKE_WINDOW", int),
        "spike_recovery_ticks": ("Trader.SPIKE_RECOVERY_TICKS", int),
        "zscore_enter": ("Trader.ZSCORE_ENTER", float),
        "zscore_exit": ("Trader.ZSCORE_EXIT", float),
        "basket_rolling_window": ("Trader.ROLLING_WINDOW", int),
        "delta_band": ("Trader.DELTA_BAND", int),
        "iv_sell_threshold": ("Trader.IV_SELL_THRESHOLD", float),
        "iv_buy_threshold": ("Trader.IV_BUY_THRESHOLD", float),
        # НЕ переписываем safety thresholds — они уже правильные (-500000) в FinalTrader.py
        # "kill_pnl_threshold": ("KillSwitch.PNL_THRESHOLD", float),
        # "kill_drawdown_threshold": ("KillSwitch.DRAWDOWN_THRESHOLD", float),
    }
    lines.append("")
    for pname, (target, typ) in _class_map.items():
        if pname in params:
            lines.append(f"{target} = {typ(params[pname])!r}")

    lines.extend(["", "# " + "=" * 70, "# END OPTIMIZED PARAMETERS", "# " + "=" * 70])

    output = source + "\n".join(lines) + "\n"
    dst_path.write_text(output, encoding="utf-8")
    backup_path.write_text(output, encoding="utf-8")  # backup copy
    print(f"\n[DEPLOY] Written {dst_path}  ({len(output):,} bytes)", flush=True)
    print(f"  Backup → {backup_path}", flush=True)
    # Signal file for monitoring
    (TRAINED_DIR / "READY").write_text(
        f"READY {time.strftime('%Y-%m-%d %H:%M:%S')} PnL={pnl_info}\n")
    return str(dst_path)


# ═══════════════════════════════════════════════════════════════════
# Results storage
# ═══════════════════════════════════════════════════════════════════
def save_results(params, pnl, validation=None):
    TRAINED_DIR.mkdir(parents=True, exist_ok=True)
    with open(BEST_PARAMS_FILE, "w") as f:
        json.dump({
            "params": params, "pnl": pnl, "validation": validation,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            "n_params": len(params),
        }, f, indent=2)
    print(f"  Saved → {BEST_PARAMS_FILE}", flush=True)


def load_results():
    if BEST_PARAMS_FILE.exists():
        with open(BEST_PARAMS_FILE) as f:
            return json.load(f)
    return None


# ═══════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="IMC4 Training Pipeline")
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--retrain", action="store_true")
    parser.add_argument("--turbo", action="store_true",
                        help="Turbo mode: 1 day/trial, Phase 1 only, 1-fold validation (~5 min)")
    parser.add_argument("--rounds", type=str, default=None)
    args = parser.parse_args()

    if args.turbo:
        args.samples = args.samples if args.samples != 2000 else 10

    print("[INIT] Discovering days...", flush=True)
    all_days = discover_days()
    print(f"  Found {len(all_days)} days: {all_days}", flush=True)
    if not all_days:
        print("[ERROR] No data!")
        sys.exit(1)

    if args.rounds:
        rounds = [int(r) for r in args.rounds.split(",")]
        all_days = [(r, d) for r, d in all_days if r in rounds]

    if args.deploy:
        saved = load_results()
        if not saved:
            print("[ERROR] No saved params")
            sys.exit(1)
        generate_trader_optimized(saved["params"], f"PnL={saved['pnl']:,.0f}")
        return

    if args.baseline:
        defaults = get_defaults()
        for r, d in all_days:
            pnl = run_single_day(defaults, r, d)
            print(f"  R{r}D{d}: {pnl:,.0f}", flush=True)
        return

    # Training pipeline
    n = args.samples
    TRAINED_DIR.mkdir(parents=True, exist_ok=True)
    random.seed(42)

    turbo = args.turbo

    if turbo:
        # Turbo: 3 days/trial (must include VOUCHER days for PnL)
        key_days = [(r, d) for r, d in all_days if r in (3, 4, 5)]  # VOUCHER rounds
        other_days = [(r, d) for r, d in all_days if r not in (3, 4, 5)]
        train_days = (key_days[:2] if key_days else []) + ([random.choice(other_days)] if other_days else [])
        if not train_days:
            train_days = random.sample(all_days, min(3, len(all_days)))
        max_days = 3
        print(f"\n[TURBO MODE] {len(train_days)} days/trial, Phase 1 only", flush=True)
    elif n <= 10:
        train_days = random.sample(all_days, min(3, len(all_days)))
        max_days = 3
    elif n <= 100:
        train_days = random.sample(all_days, min(5, len(all_days)))
        max_days = 5
    else:
        train_days = random.sample(all_days, min(8, len(all_days)))
        max_days = 8

    print(f"\n[CONFIG] Trials={n}  Params={_TOTAL_PARAMS}  Days={len(train_days)}", flush=True)

    if args.resume:
        saved = load_results()
        if saved:
            best_params, best_pnl = saved["params"], saved["pnl"]
            print(f"[RESUME] PnL={best_pnl:,.0f}", flush=True)
        else:
            best_params, best_pnl = get_defaults(), 0.0
    else:
        best_params, best_pnl = get_defaults(), 0.0

    t_start = time.time()

    # Phase 1
    best_params, best_pnl = run_optuna_phase1(n, train_days, max_days)
    save_results(best_params, best_pnl)

    if not turbo:
        # Phase 2
        best_params, best_pnl = run_decomposed_phase2(
            best_params, max(2, n // 10), train_days, max_days)
        save_results(best_params, best_pnl)

        # Phase 3
        best_params, best_pnl = local_refinement_phase3(
            best_params, max(5, n // 5), train_days, max_days)
        save_results(best_params, best_pnl)

    # Phase 4 — skip full validation in turbo (saves 40 min per round)
    if turbo:
        validation = {"mean_train": best_pnl, "mean_test": best_pnl, "overfit_pct": 0.0}
        save_results(best_params, best_pnl, validation)
    else:
        cv_folds = 2 if n <= 10 else 3
        validation = walk_forward_validate(best_params, all_days, n_folds=cv_folds)
        save_results(best_params, best_pnl, validation)

    # Phase 5: Deploy — only for non-turbo (turbo saves to best_params.json only)
    mode_tag = "[TURBO] " if turbo else ""
    pnl_info = (f"{mode_tag}PnL={best_pnl:,.0f}  OOS={validation['mean_test']:,.0f}  "
                f"Overfit={validation['overfit_pct']:+.1f}%")
    if turbo:
        print(f"\n[TURBO] Params saved to best_params.json (NOT deployed to FinalTrader.py)", flush=True)
        print(f"  Run './imc4.sh deploy-best' to apply after validation", flush=True)
    else:
        generate_trader_optimized(best_params, pnl_info)

    elapsed = time.time() - t_start
    print(f"\n{'='*60}", flush=True)
    print(f"[DONE] {elapsed/60:.1f}m  Best={best_pnl:,.0f}  OOS={validation['mean_test']:,.0f}", flush=True)


if __name__ == "__main__":
    main()
