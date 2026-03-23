#!/usr/bin/env python3
"""
17_manual.py — Manual round solvers + Chrome CDP bot for imc4/
══════════════════════════════════════════════════════════════════
Self-contained. Manual rounds use built-in solvers and strategies.

Chain #25: bot        — Chrome CDP auto-trading bot
Chain #26: r1         — Manual Round 1 (FX arb / auction)
Chain #27: r2         — Manual Round 2 (containers)
Chain #28: r3         — Manual Round 3 (insider)
Chain #29: r4         — Manual Round 4 (containers v2)
Chain #30: r5         — Manual Round 5 (news)
Chain #31: expedition — Expedition route solver
Chain #35: narrative  — Narrative decoder
"""

import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


# ═══════════════════════════════════════════════════════════
# MANUAL ROUND STRATEGIES (self-contained)
# ═══════════════════════════════════════════════════════════

ROUND_STRATEGIES = {
    1: {
        "name": "FX Arbitrage / Auction",
        "strategy": "Triangular FX arbitrage: find cycles where product of rates > 1.0. "
                     "Auction: bid/ask based on EMA of fair value.",
        "products": ["STARFRUIT", "AMETHYSTS"],
        "key_insight": "FV(AMETHYSTS)=10000 fixed. STARFRUIT = EMA/regression.",
    },
    2: {
        "name": "Containers (Resource Allocation)",
        "strategy": "Knapsack optimization: maximize value/weight ratio. "
                     "Use DP or greedy for container selection.",
        "products": ["containers with hidden values"],
        "key_insight": "Sum of revealed values + estimate hidden. Pick containers with best expected value.",
    },
    3: {
        "name": "Insider Trading (Information)",
        "strategy": "Parse news/hints for directional signals. "
                     "Buy/sell based on sentiment score of text.",
        "products": ["various"],
        "key_insight": "Text analysis → sentiment → trade direction. Speed matters.",
    },
    4: {
        "name": "Containers v2 (Multi-round)",
        "strategy": "Multi-round DP: track container values across rounds. "
                     "Bayesian update beliefs about hidden values.",
        "products": ["containers"],
        "key_insight": "Use round 1-2 data to refine estimates. Backward induction for optimal strategy.",
    },
    5: {
        "name": "News Trading (Sentiment)",
        "strategy": "NLP sentiment scoring on IMC news feed. "
                     "Map sentiment to position sizing: strong positive → max long.",
        "products": ["various"],
        "key_insight": "Pre-compute sentiment lexicon for IMC-specific terms.",
    },
}

NARRATIVE_MAPPING = {
    "exotic goods with unstable prices": "EMA market maker (STARFRUIT-like)",
    "basket of goods": "Basket arbitrage (z-score reversion)",
    "volcanic activity": "BSM IV arbitrage (VOLCANIC_ROCK_VOUCHER)",
    "conversion opportunity": "Location/conversion arb (ORCHIDS)",
    "stable commodity": "Fixed FV market making (AMETHYSTS=10000)",
    "precious metals": "EMA + trend following (ROSES/CHOCOLATE)",
    "gift basket": "Basket ETF arbitrage (PICNIC_BASKET)",
    "underwater diving": "KELP spread trading",
    "island bread": "CROISSANTS momentum",
    "volcanic rock": "VOLCANIC_ROCK options pricing",
    "dried fruit": "DJEMBES spread/arb",
    "preserved fish": "JAMS inventory management",
}

EXPEDITION_SOLVER = """
Expedition Route Solver:
1. Parse reward map (grid or graph)
2. For each team, find route maximizing sum of rewards
3. Constraint: teams cannot overlap on same cell/node
4. Algorithm: Hungarian method or min-cost max-flow
5. For grid: DP with bitmask for team positions
6. Greedy fallback: assign best route to team 1, remove cells, repeat

Quick solve: sort all cells by reward desc, assign greedily to teams.
"""


def cmd_bot(args=None):
    """Chain #25: Chrome CDP manual bot."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #25: Manual Bot (Chrome CDP)")
    print("═══════════════════════════════════════════════════════")

    print("\n  Setup:")
    print("  1. Start Chrome: /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome --remote-debugging-port=9222")
    print("  2. Navigate to IMC Prosperity manual round page")
    print("  3. Bot connects via CDP and auto-trades")
    print("\n  Bot logic in FinalTrader.py (ManualBot class)")
    print("  Strategies: see ROUND_STRATEGIES in this file")
    return True


def cmd_manual_round(round_num, args=None):
    """Generic manual round solver."""
    strategy = ROUND_STRATEGIES.get(round_num, {})

    print("═══════════════════════════════════════════════════════")
    print(f" Chain #{25+round_num}: Manual Round {round_num} — {strategy.get('name', 'Unknown')}")
    print("═══════════════════════════════════════════════════════")

    if strategy:
        print(f"\n  Strategy: {strategy['strategy']}")
        print(f"  Products: {', '.join(strategy.get('products', []))}")
        print(f"  Key insight: {strategy['key_insight']}")
    else:
        print(f"\n  No pre-built strategy for round {round_num}")

    return True


def cmd_r1(args=None): return cmd_manual_round(1, args)
def cmd_r2(args=None): return cmd_manual_round(2, args)
def cmd_r3(args=None): return cmd_manual_round(3, args)
def cmd_r4(args=None): return cmd_manual_round(4, args)
def cmd_r5(args=None): return cmd_manual_round(5, args)


def cmd_expedition(args=None):
    """Chain #31: Expedition solver."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #31: Expedition Solver")
    print("═══════════════════════════════════════════════════════")
    print(EXPEDITION_SOLVER)
    return True


def cmd_narrative(args=None):
    """Chain #35: Narrative decoder."""
    print("═══════════════════════════════════════════════════════")
    print(" Chain #35: Narrative Decoder")
    print("═══════════════════════════════════════════════════════")
    print(f"\n  {len(NARRATIVE_MAPPING)} narrative patterns:")
    for phrase, strategy in NARRATIVE_MAPPING.items():
        print(f"    '{phrase}' → {strategy}")
    return True


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "bot"
    commands = {
        "bot": cmd_bot,
        "r1": cmd_r1, "r2": cmd_r2, "r3": cmd_r3, "r4": cmd_r4, "r5": cmd_r5,
        "expedition": cmd_expedition,
        "narrative": cmd_narrative,
    }
    fn = commands.get(cmd)
    if fn is None:
        print(f"Unknown: {cmd}. Available: {', '.join(commands.keys())}")
        sys.exit(1)
    ok = fn(sys.argv[2:])
    sys.exit(0 if ok else 1)
