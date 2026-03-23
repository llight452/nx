#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# imc4.sh — Единая точка входа для 60 цепочек IMC4
# Использование: ./imc4.sh <номер_цепочки> [аргументы...]
# ═══════════════════════════════════════════════════════════════
set -e
cd "$(dirname "$0")"

# Python check
if ! command -v python3 &> /dev/null; then
    echo "[ERROR] python3 not found"
    exit 1
fi

# Ensure imc4/ is on PYTHONPATH
export PYTHONPATH="$(pwd):$(pwd)/prosperity3bt:$PYTHONPATH"

CHAIN="${1:---help}"
shift 2>/dev/null || true

case "$CHAIN" in
    # ═══ ФАЗА I — ФУНДАМЕНТ ═══
    1|24|deploy)
        echo "[Chain #24] Deploy финальный trader"
        python3 19_deploy.py deploy "$@"
        ;;
    2|58|planb)
        echo "[Chain #58] Plan B — минимальный safe trader"
        python3 19_deploy.py planb "$@"
        ;;
    3|7|baseline)
        echo "[Chain #7] Baseline бэктест (дефолты, все дни)"
        python3 16_backtest.py baseline "$@"
        ;;
    4|37|smoke)
        echo "[Chain #37] Smoke test (1 день)"
        python3 16_backtest.py smoke "$@"
        ;;
    5|1|train-quick)
        echo "[Chain #1] Train quick (10 trials)"
        python3 15_train.py --samples 10 "$@"
        ;;
    6|8|run-day)
        echo "[Chain #8] Прогон на конкретном раунде/дне"
        python3 16_backtest.py run-day "$@"
        ;;

    # ═══ ФАЗА II — ОПТИМИЗАЦИЯ ═══
    7|2|train-fast)
        echo "[Chain #2] Train fast (100 trials)"
        python3 15_train.py --samples 100 "$@"
        ;;
    8|3|train-medium)
        echo "[Chain #3] Train medium (500 trials)"
        python3 15_train.py --samples 500 "$@"
        ;;
    9|4|train-full)
        echo "[Chain #4] Train full (2000 trials)"
        python3 15_train.py --samples 2000 "$@"
        ;;
    10|5|train-resume)
        echo "[Chain #5] Train resume"
        python3 15_train.py --resume "$@"
        ;;
    11|6|deploy-best)
        echo "[Chain #6] Deploy best params"
        python3 15_train.py --deploy "$@"
        ;;
    12|9|run-all)
        echo "[Chain #9] Прогон на всех CSV"
        python3 16_backtest.py run-all "$@"
        ;;
    13|12|ab-test)
        echo "[Chain #12] A/B сравнение стратегий"
        python3 16_backtest.py ab-test "$@"
        ;;
    14|60|sensitivity)
        echo "[Chain #60] Sensitivity analysis"
        python3 20_analysis.py sensitivity "$@"
        ;;
    15|59|parallel)
        echo "[Chain #59] Параллельный бэктест"
        python3 16_backtest.py parallel "$@"
        ;;

    # ═══ ФАЗА III — ЭКСПЛОЙТЫ ═══
    16|33|prng)
        echo "[Chain #33] PRNG cracker"
        python3 18_exploits.py prng "$@"
        ;;
    17|32|har)
        echo "[Chain #32] HAR scanner"
        python3 18_exploits.py har "$@"
        ;;
    18|34|bots)
        echo "[Chain #34] Bot behavior analysis"
        python3 20_analysis.py bots "$@"
        ;;
    19|54|bot-optimize)
        echo "[Chain #54] Оптимизация под бота"
        python3 20_analysis.py bot-optimize "$@"
        ;;

    # ═══ ФАЗА IV — БИБЛИОТЕКА СТРАТЕГИЙ ═══
    20|13|strategy-existing)
        echo "[Chain #13] Existing strategy (defaults)"
        python3 16_backtest.py strategy --name baseline "$@"
        ;;
    21|14|strategy-optimized)
        echo "[Chain #14] Optimized strategy"
        python3 16_backtest.py strategy --name optimized "$@"
        ;;
    22|15|strategy-ensemble)
        echo "[Chain #15] Ensemble strategy"
        python3 16_backtest.py strategy --name ensemble "$@"
        ;;
    23|16|strategy-new)
        echo "[Chain #16] Новая стратегия из params"
        python3 16_backtest.py strategy-new "$@"
        ;;
    24|17|strategy-save)
        echo "[Chain #17] Сохранение стратегии"
        python3 16_backtest.py strategy-save "$@"
        ;;
    25|18|strategy-load)
        echo "[Chain #18] Загрузка и тест сохранённой"
        python3 16_backtest.py strategy-load "$@"
        ;;
    26|19|strategy-list)
        echo "[Chain #19] Список стратегий + PnL"
        python3 16_backtest.py strategy-list "$@"
        ;;
    27|20|tournament)
        echo "[Chain #20] Турнир стратегий"
        python3 16_backtest.py tournament "$@"
        ;;

    # ═══ ФАЗА V — P2 REPO ═══
    28|41|p2-r1)
        echo "[Chain #41] P2 Round 1"
        python3 16_backtest.py p2 --round 1 "$@"
        ;;
    29|42|p2-r2)
        echo "[Chain #42] P2 Round 2"
        python3 16_backtest.py p2 --round 2 "$@"
        ;;
    30|43|p2-r3)
        echo "[Chain #43] P2 Round 3"
        python3 16_backtest.py p2 --round 3 "$@"
        ;;
    31|44|p2-r4)
        echo "[Chain #44] P2 Round 4"
        python3 16_backtest.py p2 --round 4 "$@"
        ;;
    32|45|p2-r5)
        echo "[Chain #45] P2 Round 5"
        python3 16_backtest.py p2 --round 5 "$@"
        ;;
    33|46|p2-manual)
        echo "[Chain #46] P2 Manual notebooks"
        python3 16_backtest.py p2-manual "$@"
        ;;
    34|47|p2-compare)
        echo "[Chain #47] P2 vs FinalTrader"
        python3 16_backtest.py p2-compare "$@"
        ;;

    # ═══ ФАЗА VI — ВАЛИДАЦИЯ ═══
    35|36|pre-validate)
        echo "[Chain #36] Pre-submit validation"
        python3 19_deploy.py validate "$@"
        ;;
    36|38|full-validate)
        echo "[Chain #38] Full validation"
        python3 19_deploy.py full-validate "$@"
        ;;
    37|39|deploy-tag)
        echo "[Chain #39] Deploy + git tag"
        python3 19_deploy.py deploy-tag "$@"
        ;;
    38|40|offline)
        echo "[Chain #40] Offline pipeline"
        python3 19_deploy.py offline "$@"
        ;;
    39|10|run-new)
        echo "[Chain #10] Прогон на новых CSV"
        python3 16_backtest.py run-new "$@"
        ;;
    40|11|run-combined)
        echo "[Chain #11] Старые + новые данные"
        python3 16_backtest.py run-combined "$@"
        ;;

    # ═══ ФАЗА VII — РАУНДЫ LIVE ═══
    41|21|round-start)
        echo "[Chain #21] Round-start протокол"
        python3 14_trader.py round-start "$@"
        ;;
    42|22|adapt)
        echo "[Chain #22] Адаптация под раунд"
        python3 14_trader.py adapt "$@"
        ;;
    43|23|retrain)
        echo "[Chain #23] Re-train на данных раунда"
        python3 15_train.py --retrain "$@"
        ;;
    44|49|p3p4-map)
        echo "[Chain #49] P3→P4 mapping"
        python3 20_analysis.py p3p4-map "$@"
        ;;
    45|50|classify)
        echo "[Chain #50] Classify unknown product"
        python3 20_analysis.py classify "$@"
        ;;
    46|51|calibrate)
        echo "[Chain #51] Калибровка на live данных"
        python3 13_calibration.py "$@"
        ;;
    47|52|postmortem)
        echo "[Chain #52] Post-mortem раунда"
        python3 20_analysis.py postmortem "$@"
        ;;
    48|53|parse-logs)
        echo "[Chain #53] Parse submission logs"
        python3 20_analysis.py parse-logs "$@"
        ;;
    49|55|multi-round)
        echo "[Chain #55] Multi-round cumulative"
        python3 14_trader.py multi-round "$@"
        ;;
    50|48|leaderboard)
        echo "[Chain #48] Мониторинг leaderboard"
        python3 20_analysis.py leaderboard "$@"
        ;;
    51|56|sunlight)
        echo "[Chain #56] Sunlight/humidity data"
        python3 20_analysis.py sunlight "$@"
        ;;
    52|57|voucher)
        echo "[Chain #57] Voucher strike selection"
        python3 20_analysis.py voucher "$@"
        ;;

    # ═══ ФАЗА VIII — МАНУАЛЫ ═══
    53|25|manual-bot)
        echo "[Chain #25] Manual bot (Chrome CDP)"
        python3 17_manual.py bot "$@"
        ;;
    54|26|manual-r1)
        echo "[Chain #26] Manual R1"
        python3 17_manual.py r1 "$@"
        ;;
    55|27|manual-r2)
        echo "[Chain #27] Manual R2"
        python3 17_manual.py r2 "$@"
        ;;
    56|28|manual-r3)
        echo "[Chain #28] Manual R3"
        python3 17_manual.py r3 "$@"
        ;;
    57|29|manual-r4)
        echo "[Chain #29] Manual R4"
        python3 17_manual.py r4 "$@"
        ;;
    58|30|manual-r5)
        echo "[Chain #30] Manual R5"
        python3 17_manual.py r5 "$@"
        ;;
    59|31|expedition)
        echo "[Chain #31] Expedition solver"
        python3 17_manual.py expedition "$@"
        ;;
    60|35|narrative)
        echo "[Chain #35] Narrative decoder"
        python3 17_manual.py narrative "$@"
        ;;

    # ═══ BACKGROUND COMPUTATIONS ═══
    background|bg)
        echo "═══════════════════════════════════════════════════════"
        echo " BACKGROUND — все 11 вычислителей (одноразово)"
        echo "═══════════════════════════════════════════════════════"
        python3 21_background.py all "$@"
        ;;
    background-nonstop|bg-nonstop)
        echo "═══════════════════════════════════════════════════════"
        echo " BACKGROUND NONSTOP — 10 static + бесконечный Optuna"
        echo "═══════════════════════════════════════════════════════"
        python3 21_background.py nonstop "$@"
        ;;
    bg-status)
        echo "═══════════════════════════════════════════════════════"
        echo " PNL METHODS STATUS — 38 методов"
        echo "═══════════════════════════════════════════════════════"
        echo ""
        # Precomputed checks
        CD="data/precomputed"
        check() { [ -f "$CD/$1.DONE" ] && echo "✅ 100%" || ([ -f "$CD/$1.json" ] && echo "⏳ partial" || echo "❌   0%"); }
        printf " %-30s %15s %8s %s\n" "Метод" "Потенциал" "Прогресс" "Файл"
        echo " ────────────────────────────────────────────────────────────────────────"
        printf " %-30s %15s %8s %s\n" "PRNG Cracker"            "1,000,000+"  "❌   0%" "ждёт P4 live"
        printf " %-30s %15s %8s %s\n" "HAR Hidden API"          "500,000"     "❌   0%" "ждёт IMC сайт"
        printf " %-30s %15s %8s %s\n" "Conversion Arb"          "100,000"     "❌   0%" "ждёт P4 продукт"
        printf " %-30s %15s %8s %s\n" "Manual Bot (CDP)"        "100,000"     "❌   0%" "ждёт мануал"
        printf " %-30s %15s %8s %s\n" "Basket Hedge Calculator" "50,000"      "$(check basket_hedge)" "$CD/basket_hedge.json"
        printf " %-30s %15s %8s %s\n" "Sentiment Sizing"        "50,000"      "❌   0%" "ждёт P4 live"
        printf " %-30s %15s %8s %s\n" "Expedition Solver"       "50,000"      "❌   0%" "ждёт мануал"
        printf " %-30s %15s %8s %s\n" "Bot Model Trainer"       "30,000"      "$(check bot_models)" "$CD/bot_models.json"
        printf " %-30s %15s %8s %s\n" "Cointegration Scanner"   "20,000"      "$(check cointegration)" "$CD/cointegration.json"
        printf " %-30s %15s %8s %s\n" "Калибровка офлайн"       "20,000"      "$(check calibration)" "$CD/calibration.json"
        printf " %-30s %15s %8s %s\n" "IV Surface Builder"      "10,000"      "$(check iv_surface)" "$CD/iv_surface.json"
        # Optuna: count trials from DB
        TRIALS="?"
        if [ -f "data/trained/optuna_study.db" ]; then
            TRIALS=$(python3 -c "
import sqlite3
c=sqlite3.connect('data/trained/optuna_study.db')
print(c.execute('SELECT count(*) FROM trials').fetchone()[0])
c.close()
" 2>/dev/null || echo "?")
        fi
        printf " %-30s %15s %8s %s\n" "Optuna multi-day"        "10,000"      "⏳ ${TRIALS}t" "data/trained/optuna_study.db"
        printf " %-30s %15s %8s %s\n" "Spread Optimizer"        "10,000"      "$(check spread_optimizer)" "$CD/spread_optimizer.json"
        printf " %-30s %15s %8s %s\n" "Fair Value Regressor"    "5,000"       "$(check fair_value)" "$CD/fair_value.json"
        printf " %-30s %15s %8s %s\n" "Regime Markov Chain"     "5,000"       "$(check regime_markov)" "$CD/regime_markov.json"
        printf " %-30s %15s %8s %s\n" "Order Flow Model"        "5,000"       "$(check order_flow)" "$CD/order_flow.json"
        printf " %-30s %15s %8s %s\n" "P2 Strategy Extractor"   "5,000"       "$(check p2_strategies)" "$CD/p2_strategies.json"
        echo " ────────────────────────────────────────────────────────────────────────"
        # Runtime methods
        echo " Runtime (20 методов активны в FinalTrader.py): ✅ всегда ON"
        echo ""
        # Summary
        DONE_COUNT=$(ls "$CD"/*.DONE 2>/dev/null | wc -l | tr -d ' ')
        JSON_COUNT=$(ls "$CD"/*.json 2>/dev/null | wc -l | tr -d ' ')
        echo " Precomputed: ${DONE_COUNT} DONE, ${JSON_COUNT} JSON файлов"
        echo " Optuna trials: ${TRIALS}"
        echo ""
        echo " Запуск: ./imc4.sh bg          (все 6 вычислений)"
        echo "         ./imc4.sh bg-nonstop   (6 + бесконечный Optuna)"
        ;;

    # ═══ SPECIAL ═══
    build)
        echo "[BUILD] Сборка FinalTrader.py"
        python3 19_deploy.py build "$@"
        ;;
    status)
        echo ""
        grep -c "✅" ROADMAP.md || echo "0"
        echo " из 60 цепочек завершено"
        echo ""
        grep "🐛" ROADMAP.md || echo "Проблем нет"
        ;;
    pnl|test)
        echo "═══════════════════════════════════════════════════════"
        echo " QUICK PNL TEST — 1 день (R3D0)"
        echo "═══════════════════════════════════════════════════════"
        python3 -c "
import sys, types, time
sys.path.insert(0, '.')
from prosperity3bt.runner import run_backtest
from prosperity3bt.file_reader import PackageResourcesReader
from prosperity3bt.models import TradeMatchingMode
import importlib.util as iu
tspec = iu.spec_from_file_location('FinalTrader', 'FinalTrader.py')
tmod = types.ModuleType('FinalTrader')
tmod.__file__ = 'FinalTrader.py'
tmod.__spec__ = tspec
sys.modules['FinalTrader'] = tmod
tspec.loader.exec_module(tmod)
trader = tmod.Trader()
t0 = time.time()
result = run_backtest(trader, PackageResourcesReader(), round_num=3, day_num=0,
    print_output=False, trade_matching_mode=TradeMatchingMode.worse,
    no_names=False, show_progress_bar=False)
last_ts = max(log.columns[1] for log in result.activity_logs)
total = sum(float(log.columns[16]) for log in result.activity_logs if log.columns[1] == last_ts)
print(f'PnL R3D0: {total:+.0f}  ({time.time()-t0:.0f}s)')
from collections import defaultdict
prods = defaultdict(float)
for log in result.activity_logs:
    if log.columns[1] == last_ts:
        prods[log.columns[2]] += float(log.columns[16])
for prod, pnl in sorted(prods.items(), key=lambda x: -x[1]):
    if abs(pnl) > 0: print(f'  {prod}: {pnl:+.0f}')
print()
# Check training status
import os
db = 'data/trained/optuna_study.db'
bp = 'data/trained/best_params.json'
ready = 'data/trained/READY'
if os.path.exists(ready):
    print(open(ready).read())
if os.path.exists(bp):
    import json
    d = json.load(open(bp))
    print(f'Best params: PnL={d[\"pnl\"]}, timestamp={d[\"timestamp\"]}')
if os.path.exists(db):
    print(f'Optuna DB: {os.path.getsize(db)/1024:.0f} KB')
" "$@"
        ;;
    train-nonstop|nonstop)
        echo "═══════════════════════════════════════════════════════"
        echo " NON-STOP TRAINING — до 14 апреля 2026"
        echo " Ctrl+C чтобы остановить. Результаты аккумулируются."
        echo "═══════════════════════════════════════════════════════"
        ROUND=1
        while true; do
            echo ""
            echo "[ROUND $ROUND] $(date '+%Y-%m-%d %H:%M:%S')"
            python3 15_train.py --turbo --samples 50 "$@" 2>&1 | tee -a data/trained/nonstop.log
            ROUND=$((ROUND + 1))
            echo "[DONE] Round $ROUND. Best params saved. Sleeping 5s..."
            sleep 5
        done
        ;;
    train-full-nonstop)
        echo "═══════════════════════════════════════════════════════"
        echo " FULL NON-STOP TRAINING (slow, thorough)"
        echo "═══════════════════════════════════════════════════════"
        ROUND=1
        while true; do
            echo "[ROUND $ROUND] $(date)"
            python3 15_train.py --samples 200 "$@" 2>&1 | tee -a data/trained/nonstop_full.log
            ROUND=$((ROUND + 1))
            sleep 10
        done
        ;;
    --help|help|*)
        echo "═══════════════════════════════════════════════════════"
        echo " IMC4 — 60 цепочек"
        echo " Использование: ./imc4.sh <номер> [аргументы]"
        echo "═══════════════════════════════════════════════════════"
        echo ""
        echo "ФАЗА I:  1-6   (deploy, planb, baseline, smoke, train, run-day)"
        echo "ФАЗА II: 7-15  (train-fast/med/full, resume, deploy-best, run-all, ab, sens, parallel)"
        echo "ФАЗА III: 16-19 (prng, har, bots, bot-optimize)"
        echo "ФАЗА IV: 20-27 (strategy library, tournament)"
        echo "ФАЗА V:  28-34 (p2 rounds 1-5, manual, compare)"
        echo "ФАЗА VI: 35-40 (validate, deploy, offline, run-new/combined)"
        echo "ФАЗА VII: 41-52 (live rounds, calibration, monitoring)"
        echo "ФАЗА VIII: 53-60 (manual bot, R1-R5, expedition, narrative)"
        echo ""
        echo "Special:"
        echo "  pnl|test        — Quick PnL test (R3D0, ~90s)"
        echo "  bg              — All 11 background computations (one-shot)"
        echo "  bg-nonstop      — 10 static + infinite Optuna"
        echo "  bg-status       — Status of all 38 PnL methods"
        echo "  nonstop         — Non-stop turbo training (Ctrl+C to stop)"
        echo "  train-full-nonstop — Full non-stop training (slow)"
        echo "  build           — Build FinalTrader.py"
        echo "  status          — ROADMAP progress"
        echo "  deploy-best     — Deploy best Optuna params to FinalTrader.py"
        echo ""
        echo "60 цепочек: ./imc4.sh <1-60>"
        echo "Aliases:    ./imc4.sh deploy|planb|baseline|smoke|..."
        ;;
esac
