#!/usr/bin/env python3
"""
21_background.py — Background computations for max PnL
═══════════════════════════════════════════════════════
11 фоновых вычислителей. Каждый:
  1. Вычисляет из CSV данных
  2. Сохраняет JSON в data/precomputed/
  3. Создаёт DONE-флаг чтобы не считать повторно
  4. FinalTrader.py загружает при старте

Запуск: ./imc4.sh background    — все 7 последовательно
        python3 21_background.py basket|bots|coint|calibrate|iv|spread|optuna
"""

import json
import math
import os
import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

SCRIPT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(SCRIPT_DIR))

from prosperity3bt.file_reader import PackageResourcesReader, FileSystemReader
from prosperity3bt.data import has_day_data, read_day_data
from prosperity3bt.runner import run_backtest
from prosperity3bt.models import TradeMatchingMode

PRECOMP_DIR = SCRIPT_DIR / "data" / "precomputed"
PRECOMP_DIR.mkdir(parents=True, exist_ok=True)

STATUS_FILE = SCRIPT_DIR / "data" / "background_status.json"


# ═══════════════════════════════════════════════════════════════
# Utilities
# ═══════════════════════════════════════════════════════════════

def _done_flag(name: str) -> Path:
    return PRECOMP_DIR / f"{name}.DONE"


def _is_done(name: str) -> bool:
    return _done_flag(name).exists()


def _mark_done(name: str, info: str = ""):
    _done_flag(name).write_text(
        f"DONE {time.strftime('%Y-%m-%d %H:%M:%S')}\n{info}\n"
    )


def _save_json(name: str, data: Any):
    path = PRECOMP_DIR / f"{name}.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    print(f"  [SAVED] {path} ({path.stat().st_size / 1024:.1f} KB)")


def _update_status(name: str, status: str, details: str = ""):
    st = {}
    if STATUS_FILE.exists():
        try:
            st = json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    st[name] = {
        "status": status,
        "details": details,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    STATUS_FILE.write_text(json.dumps(st, indent=2))


def _discover_all_days() -> List[Tuple[int, int]]:
    """Discover all available days from P3 + P4."""
    days = []
    reader = PackageResourcesReader()
    for r in range(0, 10):
        for d in range(-5, 15):
            try:
                if has_day_data(reader, r, d):
                    days.append((r, d))
            except Exception:
                pass
    # P4
    p4_dir = SCRIPT_DIR / "data" / "p4_rounds"
    if p4_dir.exists():
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
                            days.append((rnum + 100, d))
                    except Exception:
                        pass
    return days


def _load_day_prices(round_num: int, day_num: int) -> Dict[str, List[float]]:
    """Load mid prices per product for a day."""
    if round_num >= 100:
        reader = FileSystemReader(SCRIPT_DIR / "data" / "p4_rounds")
        actual = round_num - 100
    else:
        reader = PackageResourcesReader()
        actual = round_num
    data = read_day_data(reader, actual, day_num, no_names=False)
    products: Dict[str, List[float]] = {}
    for ts in sorted(data.prices.keys()):
        for prod, row in data.prices[ts].items():
            products.setdefault(prod, []).append(row.mid_price)
    return products


def _load_day_trades(round_num: int, day_num: int) -> Dict[str, list]:
    """Load trades per product for a day."""
    if round_num >= 100:
        reader = FileSystemReader(SCRIPT_DIR / "data" / "p4_rounds")
        actual = round_num - 100
    else:
        reader = PackageResourcesReader()
        actual = round_num
    data = read_day_data(reader, actual, day_num, no_names=False)
    trades: Dict[str, list] = {}
    for ts in sorted(data.trades.keys()):
        for prod, tlist in data.trades[ts].items():
            for t in tlist:
                trades.setdefault(prod, []).append({
                    "ts": ts, "price": t.price, "qty": t.quantity,
                    "buyer": t.buyer, "seller": t.seller,
                })
    return trades


# ═══════════════════════════════════════════════════════════════
# 1. BASKET HEDGE CALCULATOR — потенциал +50k/день
# ═══════════════════════════════════════════════════════════════

def compute_basket_hedge():
    name = "basket_hedge"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[1/7] BASKET HEDGE CALCULATOR")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    basket_products = {
        "PICNIC_BASKET1": ["CROISSANTS", "JAMS", "DJEMBES"],
        "PICNIC_BASKET2": ["CROISSANTS", "JAMS"],
    }
    all_days = _discover_all_days()
    results = {}

    for basket, components in basket_products.items():
        print(f"\n  Basket: {basket} vs {components}")
        all_basket_prices = []
        all_comp_prices = {c: [] for c in components}
        found_days = 0

        for r, d in all_days:
            try:
                prices = _load_day_prices(r, d)
                if basket not in prices:
                    continue
                bp = prices[basket]
                cp = {c: prices.get(c, []) for c in components}
                if not all(len(v) > 10 for v in cp.values()):
                    continue
                # Align lengths
                min_len = min(len(bp), *[len(v) for v in cp.values()])
                all_basket_prices.extend(bp[:min_len])
                for c in components:
                    all_comp_prices[c].extend(cp[c][:min_len])
                found_days += 1
            except Exception:
                continue

        if found_days == 0 or len(all_basket_prices) < 50:
            print(f"    Not enough data ({found_days} days)")
            results[basket] = {"components": components, "weights": {c: 1.0 for c in components}, "found_days": 0}
            continue

        # OLS regression: basket_price = sum(w_i * comp_price_i) + intercept
        X = np.column_stack([all_comp_prices[c] for c in components])
        y = np.array(all_basket_prices)
        # Add intercept
        X_aug = np.column_stack([X, np.ones(len(y))])
        try:
            weights, residuals, _, _ = np.linalg.lstsq(X_aug, y, rcond=None)
            hedge_weights = {c: float(weights[i]) for i, c in enumerate(components)}
            intercept = float(weights[-1])
            # Residual stats
            predicted = X_aug @ weights
            resid = y - predicted
            mean_spread = float(np.mean(resid))
            std_spread = float(np.std(resid))
            print(f"    Weights: {hedge_weights}")
            print(f"    Intercept: {intercept:.2f}")
            print(f"    Spread: mean={mean_spread:.2f} std={std_spread:.2f}")
            print(f"    Days: {found_days}, datapoints: {len(y)}")

            results[basket] = {
                "components": components,
                "weights": hedge_weights,
                "intercept": intercept,
                "mean_spread": mean_spread,
                "std_spread": std_spread,
                "zscore_entry": 2.0,
                "zscore_exit": 0.5,
                "found_days": found_days,
                "datapoints": len(y),
            }
        except Exception as e:
            print(f"    Regression failed: {e}")
            results[basket] = {"components": components, "weights": {c: 1.0 for c in components}, "error": str(e)}

    _save_json(name, results)
    _mark_done(name, f"{len(results)} baskets, {sum(r.get('found_days',0) for r in results.values())} days")
    _update_status(name, "DONE", f"{len(results)} baskets computed")
    print(f"  [DONE] basket_hedge")


# ═══════════════════════════════════════════════════════════════
# 2. BOT MODEL TRAINER — потенциал +30k/день
# ═══════════════════════════════════════════════════════════════

def compute_bot_models():
    name = "bot_models"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[2/7] BOT MODEL TRAINER")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    bot_stats: Dict[str, Dict] = defaultdict(lambda: {
        "trades": 0, "buy_count": 0, "sell_count": 0,
        "avg_qty": [], "avg_price_vs_mid": [],
        "products": defaultdict(int), "timestamps": [],
    })

    for r, d in all_days:
        try:
            prices = _load_day_prices(r, d)
            trades = _load_day_trades(r, d)
            for prod, tlist in trades.items():
                mids = prices.get(prod, [])
                if not mids:
                    continue
                mid_avg = np.mean(mids)
                for t in tlist:
                    for bot_name in [t.get("buyer", ""), t.get("seller", "")]:
                        if not bot_name or bot_name == "SUBMISSION":
                            continue
                        bs = bot_stats[bot_name]
                        bs["trades"] += 1
                        if t["buyer"] == bot_name:
                            bs["buy_count"] += 1
                        else:
                            bs["sell_count"] += 1
                        bs["avg_qty"].append(abs(t["qty"]))
                        if mid_avg > 0:
                            bs["avg_price_vs_mid"].append((t["price"] - mid_avg) / mid_avg)
                        bs["products"][prod] += 1
                        bs["timestamps"].append(t["ts"])
        except Exception:
            continue

    # Summarize
    models = {}
    for bot, stats in bot_stats.items():
        if stats["trades"] < 10:
            continue
        qtys = stats["avg_qty"]
        price_devs = stats["avg_price_vs_mid"]
        ts_list = stats["timestamps"]

        # Timing pattern: do they trade at specific timestamps?
        ts_mod = [t % 1000 for t in ts_list if t > 0]
        ts_regularity = float(np.std(ts_mod)) / max(np.mean(ts_mod), 1) if ts_mod else 1.0

        # Aggression: buy vs sell ratio
        total = stats["buy_count"] + stats["sell_count"]
        buy_ratio = stats["buy_count"] / total if total > 0 else 0.5

        models[bot] = {
            "trades": stats["trades"],
            "buy_ratio": round(buy_ratio, 3),
            "avg_qty": round(float(np.mean(qtys)), 1) if qtys else 0,
            "qty_std": round(float(np.std(qtys)), 1) if qtys else 0,
            "price_aggression": round(float(np.mean(price_devs)) * 10000, 2) if price_devs else 0,
            "timing_regularity": round(ts_regularity, 3),
            "top_products": dict(sorted(stats["products"].items(), key=lambda x: -x[1])[:5]),
            "predictable": ts_regularity < 0.5 or abs(buy_ratio - 0.5) > 0.2,
        }

    print(f"  Found {len(models)} bots ({sum(1 for m in models.values() if m['predictable'])} predictable)")
    for bot, m in sorted(models.items(), key=lambda x: -x[1]["trades"])[:10]:
        pred = "PREDICTABLE" if m["predictable"] else "random"
        print(f"    {bot}: {m['trades']} trades, buy={m['buy_ratio']:.0%}, aggr={m['price_aggression']:+.1f}bps [{pred}]")

    _save_json(name, models)
    _mark_done(name, f"{len(models)} bots, {sum(1 for m in models.values() if m['predictable'])} predictable")
    _update_status(name, "DONE", f"{len(models)} bots analyzed")
    print(f"  [DONE] bot_models")


# ═══════════════════════════════════════════════════════════════
# 3. COINTEGRATION SCANNER — потенциал +20k/день
# ═══════════════════════════════════════════════════════════════

def compute_cointegration():
    name = "cointegration"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[3/7] COINTEGRATION SCANNER")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    # Collect all prices per product across all days
    all_prices: Dict[str, List[float]] = defaultdict(list)
    for r, d in all_days:
        try:
            prices = _load_day_prices(r, d)
            for prod, plist in prices.items():
                all_prices[prod].extend(plist)
        except Exception:
            continue

    products = [p for p, v in all_prices.items() if len(v) > 100]
    print(f"  Products with >100 datapoints: {len(products)}")

    # Pairwise cointegration test (simplified ADF on spread)
    pairs = []
    for i, p1 in enumerate(products):
        for p2 in products[i+1:]:
            x = np.array(all_prices[p1])
            y = np.array(all_prices[p2])
            min_len = min(len(x), len(y))
            if min_len < 100:
                continue
            x, y = x[:min_len], y[:min_len]

            # OLS: y = beta * x + alpha
            beta = np.cov(x, y)[0, 1] / np.var(x) if np.var(x) > 0 else 0
            if beta == 0:
                continue
            alpha = np.mean(y) - beta * np.mean(x)
            spread = y - beta * x - alpha

            # ADF-like test: check if spread is mean-reverting
            # Simplified: autocorrelation of spread changes
            if len(spread) < 50:
                continue
            dspread = np.diff(spread)
            if np.std(dspread) == 0:
                continue
            # Dickey-Fuller: regress dspread on lagged spread
            spread_lag = spread[:-1]
            try:
                gamma = np.cov(dspread, spread_lag)[0, 1] / np.var(spread_lag)
            except Exception:
                continue
            # gamma < 0 means mean-reverting
            half_life = -np.log(2) / gamma if gamma < 0 else float("inf")

            if gamma < -0.01 and half_life < 500:  # mean-reverting with reasonable half-life
                corr = float(np.corrcoef(x, y)[0, 1])
                pairs.append({
                    "pair": [p1, p2],
                    "beta": round(float(beta), 4),
                    "alpha": round(float(alpha), 2),
                    "gamma": round(float(gamma), 6),
                    "half_life": round(float(half_life), 1),
                    "spread_mean": round(float(np.mean(spread)), 2),
                    "spread_std": round(float(np.std(spread)), 2),
                    "correlation": round(corr, 4),
                    "datapoints": min_len,
                    "zscore_entry": 2.0,
                    "zscore_exit": 0.5,
                })

    pairs.sort(key=lambda x: x["half_life"])
    print(f"  Cointegrated pairs found: {len(pairs)}")
    for p in pairs[:10]:
        print(f"    {p['pair'][0]} — {p['pair'][1]}: beta={p['beta']}, HL={p['half_life']:.0f}, corr={p['correlation']:.3f}")

    _save_json(name, pairs)
    _mark_done(name, f"{len(pairs)} cointegrated pairs")
    _update_status(name, "DONE", f"{len(pairs)} pairs found")
    print(f"  [DONE] cointegration")


# ═══════════════════════════════════════════════════════════════
# 4. КАЛИБРОВКА ОФЛАЙН — потенциал +20k/день
# ═══════════════════════════════════════════════════════════════

def compute_calibration():
    name = "calibration"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[4/7] OFFLINE CALIBRATION")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    # Per-product stats across all days
    product_stats: Dict[str, Dict] = defaultdict(lambda: {
        "prices": [], "spreads": [], "volumes": [], "volatilities": [],
    })

    for r, d in all_days:
        try:
            if r >= 100:
                reader = FileSystemReader(SCRIPT_DIR / "data" / "p4_rounds")
                actual = r - 100
            else:
                reader = PackageResourcesReader()
                actual = r
            data = read_day_data(reader, actual, d, no_names=False)

            for ts in sorted(data.prices.keys()):
                for prod, row in data.prices[ts].items():
                    ps = product_stats[prod]
                    ps["prices"].append(row.mid_price)
                    if row.bid_prices and row.ask_prices:
                        spread = row.ask_prices[0] - row.bid_prices[0]
                        ps["spreads"].append(spread)
                    # Volume from bid/ask sizes
                    total_vol = sum(row.bid_volumes) + sum(row.ask_volumes)
                    ps["volumes"].append(total_vol)
        except Exception:
            continue

    # Compute calibrated params
    calibration = {}
    for prod, stats in product_stats.items():
        prices = stats["prices"]
        if len(prices) < 50:
            continue
        prices_arr = np.array(prices)
        returns = np.diff(prices_arr) / prices_arr[:-1]
        returns = returns[np.isfinite(returns)]

        spreads = stats["spreads"]
        volumes = stats["volumes"]

        vol = float(np.std(returns)) if len(returns) > 10 else 0.01
        mean_spread = float(np.mean(spreads)) if spreads else 1.0
        mean_vol = float(np.mean(volumes)) if volumes else 10.0
        mean_price = float(np.mean(prices))

        # Optimal EMA alpha: faster for volatile, slower for stable
        ema_alpha = min(0.5, max(0.05, vol * 10))

        # Optimal spread: just inside typical spread
        optimal_spread = max(1, int(mean_spread * 0.8))

        # Order size: inversely proportional to volatility
        optimal_size = max(1, min(50, int(10 / max(vol * 100, 0.1))))

        # AS gamma (risk aversion)
        as_gamma = min(0.15, max(0.01, vol * 5))

        calibration[prod] = {
            "mean_price": round(mean_price, 2),
            "volatility": round(vol, 6),
            "mean_spread": round(mean_spread, 2),
            "mean_volume": round(mean_vol, 1),
            "ema_alpha": round(ema_alpha, 4),
            "optimal_spread": optimal_spread,
            "optimal_size": optimal_size,
            "as_gamma": round(as_gamma, 4),
            "datapoints": len(prices),
            "is_stable": vol < 0.001,
            "is_volatile": vol > 0.01,
        }
        print(f"  {prod}: price={mean_price:.0f} vol={vol:.5f} spread={mean_spread:.1f} → ema={ema_alpha:.3f} size={optimal_size} gamma={as_gamma:.4f}")

    _save_json(name, calibration)
    _mark_done(name, f"{len(calibration)} products calibrated")
    _update_status(name, "DONE", f"{len(calibration)} products")
    print(f"  [DONE] calibration")


# ═══════════════════════════════════════════════════════════════
# 5. IV SURFACE BUILDER — потенциал +10k/день
# ═══════════════════════════════════════════════════════════════

def compute_iv_surface():
    name = "iv_surface"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[5/7] IV SURFACE BUILDER")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    # Collect VOLCANIC_ROCK + VOUCHER prices
    rock_prices: List[float] = []
    voucher_data: Dict[str, List[Dict]] = defaultdict(list)  # strike -> [{rock_mid, voucher_mid, ts}]

    strikes = {
        "VOLCANIC_ROCK_VOUCHER_9500": 9500,
        "VOLCANIC_ROCK_VOUCHER_9750": 9750,
        "VOLCANIC_ROCK_VOUCHER_10000": 10000,
        "VOLCANIC_ROCK_VOUCHER_10250": 10250,
        "VOLCANIC_ROCK_VOUCHER_10500": 10500,
    }

    for r, d in all_days:
        try:
            if r >= 100:
                reader = FileSystemReader(SCRIPT_DIR / "data" / "p4_rounds")
                actual = r - 100
            else:
                reader = PackageResourcesReader()
                actual = r
            data = read_day_data(reader, actual, d, no_names=False)

            for ts in sorted(data.prices.keys()):
                rock_row = data.prices[ts].get("VOLCANIC_ROCK")
                if rock_row is None:
                    continue
                rock_mid = rock_row.mid_price
                rock_prices.append(rock_mid)

                for voucher_name, strike in strikes.items():
                    v_row = data.prices[ts].get(voucher_name)
                    if v_row is None:
                        continue
                    voucher_data[voucher_name].append({
                        "rock_mid": rock_mid,
                        "voucher_mid": v_row.mid_price,
                        "strike": strike,
                        "ts": ts,
                    })
        except Exception:
            continue

    if not rock_prices:
        print("  No VOLCANIC_ROCK data found")
        _save_json(name, {"error": "no data"})
        _mark_done(name, "no VOLCANIC_ROCK data")
        _update_status(name, "DONE", "no data")
        return

    # BSM implied vol calculation
    def bs_call(S, K, T, sigma):
        if T <= 0 or sigma <= 0:
            return max(0, S - K)
        d1 = (math.log(S / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)
        # Normal CDF approximation
        def ncdf(x):
            return 0.5 * (1.0 + math.erf(x / math.sqrt(2)))
        return S * ncdf(d1) - K * ncdf(d2)

    def implied_vol(S, K, T, market_price):
        if market_price <= max(0, S - K):
            return 0.0
        lo, hi = 0.01, 5.0
        for _ in range(50):
            mid = (lo + hi) / 2
            if bs_call(S, K, T, mid) > market_price:
                hi = mid
            else:
                lo = mid
        return (lo + hi) / 2

    # T ≈ days remaining / 252 (assume mid-expiry ≈ 5 days)
    T = 5 / 252
    surface = {}

    for voucher_name, vdata in voucher_data.items():
        strike = strikes[voucher_name]
        ivs = []
        for d in vdata:
            try:
                iv = implied_vol(d["rock_mid"], strike, T, d["voucher_mid"])
                if 0.01 < iv < 5.0:
                    ivs.append(iv)
            except Exception:
                continue

        if ivs:
            surface[voucher_name] = {
                "strike": strike,
                "mean_iv": round(float(np.mean(ivs)), 4),
                "std_iv": round(float(np.std(ivs)), 4),
                "min_iv": round(float(np.min(ivs)), 4),
                "max_iv": round(float(np.max(ivs)), 4),
                "median_iv": round(float(np.median(ivs)), 4),
                "datapoints": len(ivs),
                "moneyness": round(float(np.mean([d["rock_mid"] for d in vdata])) / strike, 4),
            }
            print(f"  {voucher_name} (K={strike}): IV={np.mean(ivs):.3f} ± {np.std(ivs):.3f} ({len(ivs)} pts)")

    # Smile parameters
    if len(surface) >= 3:
        strikes_arr = [surface[v]["strike"] for v in sorted(surface)]
        ivs_arr = [surface[v]["mean_iv"] for v in sorted(surface)]
        # Quadratic fit: IV = a*(K-ATM)^2 + b*(K-ATM) + c
        atm_strike = 10000
        x = [k - atm_strike for k in strikes_arr]
        if len(x) >= 3:
            coeffs = np.polyfit(x, ivs_arr, 2)
            surface["_smile_params"] = {
                "a": round(float(coeffs[0]), 10),
                "b": round(float(coeffs[1]), 6),
                "c": round(float(coeffs[2]), 4),
                "atm_strike": atm_strike,
                "atm_iv": round(float(np.polyval(coeffs, 0)), 4),
            }
            print(f"  Smile: a={coeffs[0]:.2e} b={coeffs[1]:.4f} c={coeffs[2]:.4f}")

    surface["_rock_stats"] = {
        "mean": round(float(np.mean(rock_prices)), 2),
        "std": round(float(np.std(rock_prices)), 2),
        "datapoints": len(rock_prices),
    }

    _save_json(name, surface)
    _mark_done(name, f"{len(surface)-1} strikes, {len(rock_prices)} rock prices")
    _update_status(name, "DONE", f"{len(surface)-1} strikes")
    print(f"  [DONE] iv_surface")


# ═══════════════════════════════════════════════════════════════
# 6. SPREAD OPTIMIZER — потенциал +10k/день
# ═══════════════════════════════════════════════════════════════

def compute_spread_optimizer():
    name = "spread_optimizer"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[6/7] SPREAD OPTIMIZER")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    # Per-product: collect spread distributions and fill rates
    product_spreads: Dict[str, List[Dict]] = defaultdict(list)

    for r, d in all_days:
        try:
            if r >= 100:
                reader = FileSystemReader(SCRIPT_DIR / "data" / "p4_rounds")
                actual = r - 100
            else:
                reader = PackageResourcesReader()
                actual = r
            data = read_day_data(reader, actual, d, no_names=False)

            # Collect spread at each timestamp
            for ts in sorted(data.prices.keys()):
                for prod, row in data.prices[ts].items():
                    if row.bid_prices and row.ask_prices:
                        spread = row.ask_prices[0] - row.bid_prices[0]
                        bid_vol = row.bid_volumes[0] if row.bid_volumes else 0
                        ask_vol = row.ask_volumes[0] if row.ask_volumes else 0
                        # Check if trades happened at this timestamp
                        trades_at_ts = data.trades.get(ts, {}).get(prod, [])
                        had_fill = len(trades_at_ts) > 0
                        product_spreads[prod].append({
                            "spread": spread,
                            "mid": row.mid_price,
                            "bid_vol": bid_vol,
                            "ask_vol": ask_vol,
                            "had_fill": had_fill,
                        })
        except Exception:
            continue

    results = {}
    for prod, sdata in product_spreads.items():
        if len(sdata) < 50:
            continue
        spreads = [s["spread"] for s in sdata]
        mids = [s["mid"] for s in sdata]
        fills = [s for s in sdata if s["had_fill"]]
        fill_rate = len(fills) / len(sdata)

        # Spreads where fills happened
        fill_spreads = [s["spread"] for s in fills] if fills else spreads

        # Optimal: just inside median spread for fills
        median_spread = float(np.median(spreads))
        fill_median = float(np.median(fill_spreads)) if fill_spreads else median_spread

        # Our optimal: slightly tighter than market to get fills
        optimal = max(1, int(fill_median * 0.9))

        results[prod] = {
            "median_spread": round(median_spread, 2),
            "mean_spread": round(float(np.mean(spreads)), 2),
            "min_spread": round(float(np.min(spreads)), 2),
            "p25_spread": round(float(np.percentile(spreads, 25)), 2),
            "p75_spread": round(float(np.percentile(spreads, 75)), 2),
            "fill_rate": round(fill_rate, 4),
            "fill_median_spread": round(fill_median, 2),
            "optimal_spread": optimal,
            "mean_price": round(float(np.mean(mids)), 2),
            "spread_bps": round(median_spread / float(np.mean(mids)) * 10000, 2) if np.mean(mids) > 0 else 0,
            "datapoints": len(sdata),
        }
        print(f"  {prod}: spread={median_spread:.1f} fill_rate={fill_rate:.1%} optimal={optimal} ({len(sdata)} pts)")

    _save_json(name, results)
    _mark_done(name, f"{len(results)} products")
    _update_status(name, "DONE", f"{len(results)} products optimized")
    print(f"  [DONE] spread_optimizer")


# ═══════════════════════════════════════════════════════════════
# 7. FAIR VALUE REGRESSOR — потенциал +5k/день
# ═══════════════════════════════════════════════════════════════

def compute_fair_value():
    name = "fair_value"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[7/11] FAIR VALUE REGRESSOR")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    results = {}

    # Collect price series per product across all days
    product_all_prices: Dict[str, List[float]] = {}
    for r, d in all_days:
        try:
            prices = _load_day_prices(r, d)
            for prod, plist in prices.items():
                product_all_prices.setdefault(prod, []).extend(plist)
        except Exception:
            pass

    for prod, prices in product_all_prices.items():
        if len(prices) < 100:
            continue
        arr = np.array(prices)
        # Fair value = EMA with optimal alpha (minimize prediction error)
        best_alpha = 0.1
        best_err = float("inf")
        for alpha in [0.01, 0.02, 0.05, 0.1, 0.15, 0.2, 0.3, 0.5]:
            ema = arr[0]
            errors = []
            for i in range(1, len(arr)):
                pred = ema
                actual = arr[i]
                errors.append((actual - pred) ** 2)
                ema = alpha * actual + (1 - alpha) * ema
            mse = np.mean(errors)
            if mse < best_err:
                best_err = mse
                best_alpha = alpha

        # Compute regression features: trend, momentum, mean-reversion speed
        returns = np.diff(arr) / arr[:-1]
        autocorr = float(np.corrcoef(returns[:-1], returns[1:])[0, 1]) if len(returns) > 2 else 0
        mean_price = float(np.mean(arr))
        vol = float(np.std(returns)) if len(returns) > 1 else 0
        trend = float(np.polyfit(range(min(200, len(arr))), arr[-min(200, len(arr)):], 1)[0])

        results[prod] = {
            "mean_price": mean_price,
            "optimal_ema_alpha": best_alpha,
            "prediction_mse": float(best_err),
            "volatility": vol,
            "autocorrelation": autocorr,
            "trend_slope": trend,
            "mean_reversion": autocorr < -0.1,
            "datapoints": len(arr),
        }
        print(f"  {prod}: fv={mean_price:.2f} alpha={best_alpha} autocorr={autocorr:.3f} vol={vol:.5f}")

    _save_json(name, results)
    _mark_done(name, f"{len(results)} products")
    _update_status(name, "DONE", f"{len(results)} products")
    print(f"  [DONE] fair_value ({len(results)} products)")


# ═══════════════════════════════════════════════════════════════
# 8. REGIME MARKOV CHAIN — потенциал +5k/день
# ═══════════════════════════════════════════════════════════════

def compute_regime_markov():
    name = "regime_markov"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[8/11] REGIME MARKOV CHAIN")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    results = {}

    product_all_prices: Dict[str, List[float]] = {}
    for r, d in all_days:
        try:
            prices = _load_day_prices(r, d)
            for prod, plist in prices.items():
                product_all_prices.setdefault(prod, []).extend(plist)
        except Exception:
            pass

    for prod, prices in product_all_prices.items():
        if len(prices) < 200:
            continue
        arr = np.array(prices)
        returns = np.diff(arr) / arr[:-1]
        vol_window = 20

        # Classify each window into regime: low_vol, medium_vol, high_vol, trending_up, trending_down
        regimes = []
        for i in range(vol_window, len(returns)):
            window = returns[i - vol_window:i]
            v = np.std(window)
            m = np.mean(window)
            if v < np.percentile(np.abs(returns), 25):
                regime = 0  # low vol
            elif v > np.percentile(np.abs(returns), 75):
                regime = 2  # high vol
            else:
                regime = 1  # medium vol
            if m > 0.001:
                regime += 3  # trending up
            elif m < -0.001:
                regime += 6  # trending down
            regimes.append(min(regime, 8))

        # Transition matrix 9x9
        n_states = 9
        trans = np.zeros((n_states, n_states))
        for i in range(len(regimes) - 1):
            trans[regimes[i]][regimes[i + 1]] += 1

        # Normalize
        row_sums = trans.sum(axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1
        trans_prob = trans / row_sums

        # Stationary distribution
        try:
            eigenvalues, eigenvectors = np.linalg.eig(trans_prob.T)
            idx = np.argmin(np.abs(eigenvalues - 1.0))
            stationary = np.real(eigenvectors[:, idx])
            stationary = stationary / stationary.sum()
        except Exception:
            stationary = np.ones(n_states) / n_states

        results[prod] = {
            "transition_matrix": trans_prob.tolist(),
            "stationary_distribution": stationary.tolist(),
            "regime_names": ["low_vol", "med_vol", "high_vol",
                            "low_up", "med_up", "high_up",
                            "low_down", "med_down", "high_down"],
            "most_common_regime": int(np.argmax(stationary)),
            "datapoints": len(prices),
        }
        regime_name = results[prod]["regime_names"][results[prod]["most_common_regime"]]
        print(f"  {prod}: dominant={regime_name} ({stationary[results[prod]['most_common_regime']]:.1%})")

    _save_json(name, results)
    _mark_done(name, f"{len(results)} products")
    _update_status(name, "DONE", f"{len(results)} products")
    print(f"  [DONE] regime_markov ({len(results)} products)")


# ═══════════════════════════════════════════════════════════════
# 9. ORDER FLOW MODEL — потенциал +5k/день
# ═══════════════════════════════════════════════════════════════

def compute_order_flow():
    name = "order_flow"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[9/11] ORDER FLOW MODEL")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    all_days = _discover_all_days()
    results = {}

    product_trades: Dict[str, list] = {}
    product_prices: Dict[str, List[float]] = {}

    for r, d in all_days:
        try:
            trades = _load_day_trades(r, d)
            prices = _load_day_prices(r, d)
            for prod, tlist in trades.items():
                product_trades.setdefault(prod, []).extend(tlist)
            for prod, plist in prices.items():
                product_prices.setdefault(prod, []).extend(plist)
        except Exception:
            pass

    for prod in product_trades:
        tlist = product_trades[prod]
        plist = product_prices.get(prod, [])
        if len(tlist) < 50 or len(plist) < 50:
            continue

        # Compute OFI: buy_volume - sell_volume per window
        buy_vol = sum(t["qty"] for t in tlist if t.get("buyer") and not t.get("seller"))
        sell_vol = sum(t["qty"] for t in tlist if t.get("seller") and not t.get("buyer"))
        total_vol = buy_vol + sell_vol
        ofi_ratio = (buy_vol - sell_vol) / max(1, total_vol)

        # Price impact: how much price moves per unit OFI
        arr = np.array(plist)
        returns = np.diff(arr) / arr[:-1] if len(arr) > 1 else np.array([0])
        avg_return = float(np.mean(returns))
        vol = float(np.std(returns)) if len(returns) > 1 else 0

        # Toxic flow detection: large trades against the trend
        trade_sizes = [t["qty"] for t in tlist]
        large_threshold = np.percentile(trade_sizes, 90) if trade_sizes else 10
        toxic_trades = [t for t in tlist if t["qty"] > large_threshold]
        toxic_ratio = len(toxic_trades) / max(1, len(tlist))

        results[prod] = {
            "buy_volume": buy_vol,
            "sell_volume": sell_vol,
            "ofi_ratio": ofi_ratio,
            "avg_trade_size": float(np.mean(trade_sizes)) if trade_sizes else 0,
            "large_trade_threshold": float(large_threshold),
            "toxic_flow_ratio": toxic_ratio,
            "price_impact_bps": avg_return * 10000,
            "volatility": vol,
            "total_trades": len(tlist),
            "datapoints": len(plist),
        }
        print(f"  {prod}: OFI={ofi_ratio:.3f} toxic={toxic_ratio:.1%} trades={len(tlist)}")

    _save_json(name, results)
    _mark_done(name, f"{len(results)} products")
    _update_status(name, "DONE", f"{len(results)} products")
    print(f"  [DONE] order_flow ({len(results)} products)")


# ═══════════════════════════════════════════════════════════════
# 10. P2 STRATEGY EXTRACTOR — потенциал +5k/день
# ═══════════════════════════════════════════════════════════════

def compute_p2_strategies():
    name = "p2_strategies"
    if _is_done(name):
        print(f"[SKIP] {name} already done")
        return
    print(f"\n{'='*60}")
    print(f"[10/11] P2 STRATEGY EXTRACTOR")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    p2_dir = SCRIPT_DIR / "p2_repo"
    results = {}

    if not p2_dir.exists():
        print("  [SKIP] p2_repo/ not found")
        _mark_done(name, "no p2_repo")
        _update_status(name, "DONE", "no p2_repo")
        return

    # Scan all .py files in p2_repo for strategy patterns
    import re
    strategy_patterns = {
        "fair_value": re.compile(r"fair_value\s*=\s*(\d+\.?\d*)"),
        "spread": re.compile(r"spread\s*=\s*(\d+\.?\d*)"),
        "position_limit": re.compile(r"position_limit\s*=\s*(\d+)"),
        "ema_alpha": re.compile(r"(?:ema_alpha|alpha)\s*=\s*(\d+\.?\d*)"),
        "window": re.compile(r"(?:window|lookback)\s*=\s*(\d+)"),
        "threshold": re.compile(r"(?:threshold|zscore)\s*=\s*(\d+\.?\d*)"),
    }

    for py_file in sorted(p2_dir.rglob("*.py")):
        rel = str(py_file.relative_to(p2_dir))
        try:
            code = py_file.read_text(errors="ignore")
        except Exception:
            continue

        found = {}
        for param_name, pattern in strategy_patterns.items():
            matches = pattern.findall(code)
            if matches:
                found[param_name] = [float(m) for m in matches]

        if found:
            results[rel] = {
                "params": {k: v for k, v in found.items()},
                "lines": len(code.splitlines()),
            }
            print(f"  {rel}: {list(found.keys())}")

    _save_json(name, results)
    _mark_done(name, f"{len(results)} files")
    _update_status(name, "DONE", f"{len(results)} strategy files extracted")
    print(f"  [DONE] p2_strategies ({len(results)} files)")


# ═══════════════════════════════════════════════════════════════
# 11. OPTUNA MULTI-DAY (robust) — потенциал +10k/день
# ═══════════════════════════════════════════════════════════════

def compute_optuna_multiday():
    name = "optuna_multiday"
    # This one doesn't use DONE flag — always continues
    print(f"\n{'='*60}")
    print(f"[7/7] OPTUNA MULTI-DAY (robust)")
    print(f"{'='*60}")
    _update_status(name, "RUNNING")

    # Import and run training with multi-day validation
    import subprocess
    result = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "15_train.py"), "--samples", "50"],
        capture_output=True, text=True, timeout=3600,
    )
    print(result.stdout[-2000:] if result.stdout else "no output")
    if result.returncode == 0:
        _update_status(name, "DONE", "50 trials completed")
    else:
        print(f"  ERROR: {result.stderr[-500:]}")
        _update_status(name, "ERROR", result.stderr[-200:])

    print(f"  [DONE] optuna_multiday")


# ═══════════════════════════════════════════════════════════════
# MAIN — run all or specific
# ═══════════════════════════════════════════════════════════════

COMPUTERS = {
    "basket": compute_basket_hedge,
    "bots": compute_bot_models,
    "coint": compute_cointegration,
    "calibrate": compute_calibration,
    "iv": compute_iv_surface,
    "spread": compute_spread_optimizer,
    "fairvalue": compute_fair_value,
    "regime": compute_regime_markov,
    "orderflow": compute_order_flow,
    "p2strat": compute_p2_strategies,
    "optuna": compute_optuna_multiday,
}


def run_all():
    """Run all 7 in order of potential."""
    t0 = time.time()
    print("=" * 60)
    print(" BACKGROUND COMPUTATIONS — ALL 7")
    print(f" {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)

    for name, fn in COMPUTERS.items():
        try:
            fn()
        except Exception as e:
            print(f"\n  [ERROR] {name}: {e}")
            _update_status(name, "ERROR", str(e))

    elapsed = time.time() - t0
    print(f"\n{'='*60}")
    print(f" ALL DONE in {elapsed/60:.1f} min")
    print(f" Results in: {PRECOMP_DIR}/")
    print(f" Status: {STATUS_FILE}")
    print(f"{'='*60}")

    # Summary
    if STATUS_FILE.exists():
        st = json.loads(STATUS_FILE.read_text())
        for name, info in st.items():
            print(f"  {name}: {info['status']} — {info.get('details','')}")


def run_nonstop():
    """Run all, then loop optuna forever."""
    # First pass: compute all 6 static ones
    for name in ["basket", "bots", "coint", "calibrate", "iv", "spread", "fairvalue", "regime", "orderflow", "p2strat"]:
        try:
            COMPUTERS[name]()
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")

    # Then loop optuna forever
    print(f"\n{'='*60}")
    print(f" STATIC DONE — Starting infinite Optuna loop")
    print(f"{'='*60}")

    round_num = 1
    while True:
        print(f"\n[OPTUNA ROUND {round_num}] {time.strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            compute_optuna_multiday()
        except Exception as e:
            print(f"  [ERROR] optuna round {round_num}: {e}")
        round_num += 1
        time.sleep(5)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"

    if cmd == "all":
        run_all()
    elif cmd == "nonstop":
        run_nonstop()
    elif cmd in COMPUTERS:
        COMPUTERS[cmd]()
    elif cmd == "status":
        if STATUS_FILE.exists():
            st = json.loads(STATUS_FILE.read_text())
            for name, info in st.items():
                done = "✅" if info["status"] == "DONE" else "❌" if info["status"] == "ERROR" else "⏳"
                print(f"  {done} {name}: {info['status']} — {info.get('details','')} ({info.get('timestamp','')})")
        else:
            print("  No background computations run yet")
        # Check DONE flags
        for name in COMPUTERS:
            flag = _done_flag(name)
            if flag.exists():
                print(f"  📁 {flag.name}: {flag.read_text().strip()[:80]}")
    else:
        print(f"Unknown: {cmd}")
        print(f"Available: {', '.join(COMPUTERS.keys())}, all, nonstop, status")
        sys.exit(1)
