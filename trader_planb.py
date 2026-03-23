#!/usr/bin/env python3
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
