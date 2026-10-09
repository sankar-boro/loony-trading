#!/usr/bin/env python3
"""
Loony Trading Bot — Main Entry Point

Primary market: Upstox (Indian equities & F&O)
Secondary market: Binance (crypto)

Usage:
  python main.py                         # paper trade Indian markets
  python main.py --mode live             # live trade (requires Upstox token)
  python main.py --mode backtest         # backtest on historical data
  python main.py --mode backtest --market crypto
  python main.py --mode train            # retrain ML models
  python main.py --mode auth             # run Upstox OAuth flow
"""
import asyncio
import argparse
import sys
import time
from pathlib import Path

from config import settings
from utils.logger import get_logger
from utils.notifier import Notifier
from utils.trade_logger import TradeLogger

logger = get_logger("main", level=settings.get("system.log_level", "INFO"))

ROOT = Path(__file__).resolve().parent
STATE_FILE = ROOT / "data" / "live_positions.json"   # also read by the dashboard
_STATE_HEARTBEAT_SEC = 5   # rewrite at least this often so the dashboard sees the bot as running


# ── Upstox Bot ─────────────────────────────────────────────────────────────────

class UpstoxTradingBot:
    """
    Upstox-first trading bot for Indian equity and F&O markets.
    Uses WebSocket feed for real-time prices and the full strategy stack.
    """

    def __init__(self, cfg: dict, mode: str = "paper"):
        from data_engine.upstox import UpstoxAuth, InstrumentRegistry, UpstoxDataEngine, UpstoxFeed
        from data_engine.live_bars import LiveBarAggregator
        from execution_engine.upstox_executor import UpstoxExecutor, UpstoxProduct
        from risk_manager import RiskManager
        from portfolio_manager import PortfolioManager
        from strategies.meta_engine import MetaStrategyEngine
        from ml_models import ModelTrainer

        self.cfg = cfg
        self.mode = mode
        self.notifier = Notifier(cfg.get("notifications", {}))
        self.trade_logger = TradeLogger()

        # Capital in INR
        initial_capital = cfg.get("portfolio", {}).get("initial_capital", 500_000)

        # Symbols
        self.equity_symbols: list[str] = cfg.get("assets", {}).get("india_equity", [])
        self.index_symbols:  list[str] = cfg.get("assets", {}).get("india_indices", [])
        self.all_symbols = self.equity_symbols + self.index_symbols
        self.primary_tf = cfg.get("timeframes", {}).get("primary", "1d")
        self.intraday_tf = cfg.get("timeframes", {}).get("intraday", "15m")

        # Auth
        up_cfg = cfg.get("exchanges", {}).get("upstox", {})
        self.auth = UpstoxAuth(
            api_key=up_cfg.get("api_key", ""),
            api_secret=up_cfg.get("api_secret", ""),
            redirect_uri=up_cfg.get("redirect_uri", "http://localhost:3561/callback"),
            token_file=up_cfg.get("token_file", "data/upstox_token.json"),
        )

        # Try loading existing token first
        token = self.auth.load_token()
        if not token and up_cfg.get("access_token"):
            # Token passed via env var
            from data_engine.upstox.auth import _AUTH_BASE
            import time
            self.auth._token_data = {
                "access_token": up_cfg["access_token"],
                "obtained_at": time.time(),
            }

        # Instrument registry
        self.registry = InstrumentRegistry()
        self.registry.load(exchanges=["NSE_EQ", "NSE_FO", "NSE_INDEX"])

        # Data engine
        self.data_engine = UpstoxDataEngine(self.auth, self.registry)

        # WebSocket feed
        self.feed = UpstoxFeed(self.auth, self.registry, mode="full")
        self.feed.subscribe(self._on_tick)

        # Risk + portfolio
        self.risk_manager = RiskManager(cfg, initial_capital)
        self.portfolio = PortfolioManager(cfg, initial_capital)

        # Execution (the executor reads exchanges.upstox.default_product itself)
        self.executor = UpstoxExecutor(
            self.auth, self.registry, self.risk_manager, cfg, mode=mode
        )
        self.executor.on_fill(self._on_fill)

        # Strategy engine + ML
        self.meta_engine = MetaStrategyEngine(cfg, ml_model=None)
        self._trainer = ModelTrainer(cfg)
        self._df_cache: dict = {}   # symbol → DataFrame — read by strategies, kept fresh intraday (see _refresh_live_df)
        self._df_cache_base: dict = {}   # immutable historical fetch, before today's live bars are spliced on
        self._live_bars = LiveBarAggregator()   # docs/intraday_gaps.md §1 fix — turns live ticks into fresh bars
        self._tick_counter: dict = {}
        self._mis_squareoff_date = None   # IST date the MIS squareoff last ran
        self._last_price: dict[str, float] = {}
        self._state_file = STATE_FILE
        self._state_saved_version = -1
        self._state_saved_at = 0.0
        self._recon_strikes: dict[str, int] = {}   # instrument key → consecutive mismatches
        self._recon_alerted: set = set()            # (date, key) already alerted as untracked
        self._recon_task = None
        self._suspect_ticks: dict[str, list[float]] = {}   # symbol → rejected prices in a row

    # ── Startup ────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        from data_engine.upstox.market_hours import is_market_open, next_market_open, now_ist

        logger.info(f"Loony Trading Bot starting [{self.mode.upper()}] — Indian Markets (Upstox)")
        logger.info(f"Symbols: {', '.join(self.all_symbols[:10])}{'...' if len(self.all_symbols) > 10 else ''}")

        # Token age check — hard block for live, warning for paper
        token_age_h = (time.time() - self.auth._token_data.get("obtained_at", 0)) / 3600
        if not self.auth.is_valid():
            if self.mode == "live":
                logger.error(
                    f"Upstox token is expired or missing (age {token_age_h:.1f}h). "
                    "Run: python main.py --mode auth  OR  bash scripts/auto_login.sh"
                )
                return
            else:
                logger.warning(
                    f"Upstox token is expired (age {token_age_h:.1f}h). "
                    "Paper mode continuing but API calls may fail."
                )
        else:
            from data_engine.upstox.auth import token_hours_left
            hours_left = token_hours_left(self.auth._token_data.get("obtained_at", 0))
            if hours_left <= 3:
                logger.warning(
                    f"Upstox token expires in {hours_left:.1f}h (03:30 IST). "
                    "Run: bash scripts/auto_login.sh"
                )

        self._restore_state()
        self._check_ml_models()
        await self._load_historical_data()
        await self._train_or_load_models()

        if not is_market_open():
            nxt = next_market_open()
            logger.info(f"Market is closed. Next open: {nxt.strftime('%Y-%m-%d %H:%M IST')}")
            if self.mode == "paper":
                logger.info("Paper mode: starting polling on cached data for testing")
                await self._run_paper_simulation()
                return

        if self.mode == "live":
            await self._reconcile(at_startup=True)
            self._recon_task = asyncio.create_task(self._reconcile_loop())

        logger.info("Starting real-time WebSocket feed...")
        await self.feed.start(self.all_symbols, mode="full")

    def _check_ml_models(self) -> None:
        # One shared model, not one per symbol: MetaStrategyEngine loads
        # models/ensemble.pkl (written by scripts/train_ml.py), and
        # _train_or_load_models falls back to models/xgboost.pkl + lightgbm.pkl.
        models_dir = Path(__file__).resolve().parent / "models"
        if (models_dir / "ensemble.pkl").exists():
            logger.info("ML model found: models/ensemble.pkl")
        elif (models_dir / "xgboost.pkl").exists() and (models_dir / "lightgbm.pkl").exists():
            logger.info("ML models found: models/xgboost.pkl + models/lightgbm.pkl")
        else:
            logger.warning(
                "No trained ML model in models/ — MLClassifierStrategy will not fire. "
                "Run: python scripts/train_ml.py"
            )

    async def _load_historical_data(self) -> None:
        lookback = self.cfg.get("data", {}).get("lookback_days", 365)
        logger.info(f"Loading historical data ({lookback} days) for {len(self.all_symbols)} symbols...")
        self._live_bars.clear()   # a fresh run must never inherit a previous session's live bars
        for sym in self.all_symbols:
            df = self.data_engine.fetch_ohlcv(sym, self.primary_tf, lookback_days=lookback)
            if not df.empty:
                self._df_cache[sym] = df
                logger.info(f"  {sym}: {len(df)} bars ({self.primary_tf})")

        # Also fetch intraday for every equity symbol, so none of them falls
        # back to the (never refreshed) daily cache. A short pause between
        # requests keeps us under Upstox's historical-API rate limit.
        if self.intraday_tf != self.primary_tf:
            for i, sym in enumerate(self.equity_symbols):
                if i:
                    await asyncio.sleep(0.25)
                df_intra = self.data_engine.fetch_ohlcv(sym, self.intraday_tf,
                                                         lookback_days=60)
                if not df_intra.empty:
                    key = f"{sym}_{self.intraday_tf}"
                    self._df_cache[key] = df_intra
                    self._df_cache_base[key] = df_intra   # kept as the pre-session base — see _refresh_live_df

    async def _train_or_load_models(self) -> None:
        from ml_models import XGBoostModel, LightGBMModel, EnsembleModel

        if self.meta_engine.has_ml_model():
            return   # models/ensemble.pkl was already loaded by MetaStrategyEngine

        xgb  = XGBoostModel(self.cfg)
        lgbm = LightGBMModel(self.cfg)
        if xgb.load() and lgbm.load():
            model = EnsembleModel([xgb, lgbm])
            self.meta_engine.update_ml_model(model)
            logger.info("Loaded pretrained ML models")
            return

        train_sym = self.equity_symbols[0] if self.equity_symbols else None
        if train_sym and train_sym in self._df_cache:
            df = self._df_cache[train_sym]
            if len(df) > 300:
                logger.info(f"Training ML models on {train_sym}...")
                loop = asyncio.get_running_loop()
                ensemble = await loop.run_in_executor(None, self._trainer.train_all, df)
                if ensemble:
                    self.meta_engine.update_ml_model(ensemble)
                    logger.info("ML models trained")

    # ── Tick handler (real-time) ────────────────────────────────────────────────

    def _refresh_live_df(self, symbol: str) -> None:
        """Splice today's freshly-aggregated intraday bars onto the
        pre-session historical base and update _df_cache — the fix for
        docs/intraday_gaps.md §1 (the live loop previously never updated
        the dataframe strategies actually score against)."""
        from data_engine.live_bars import merge_live_onto_history
        key = f"{symbol}_{self.intraday_tf}"
        base = self._df_cache_base.get(key)
        live = self._live_bars.get_bars(symbol, self.intraday_tf)
        self._df_cache[key] = merge_live_onto_history(base, live)

    def _is_intraday_product(self) -> bool:
        return self.executor._default_product.value == "MIS"

    async def _close_tracked(self, pos, price: float, reason: str, send_order: bool = True) -> None:
        """Close a position the bot is tracking. With send_order=False the
        position is only removed from the books (the broker already closed it)."""
        if send_order:
            order = await self.executor.close_position(pos, price, reason)
            if not order:
                return
            pnl = pos.pnl   # set by RiskManager.close_position at the fill price
        else:
            pnl = self.risk_manager.close_position(pos, price, reason)
        self.trade_logger.log_position_close(pos, price, pnl, reason)
        self.portfolio.record_trade(pos.symbol, pnl, pos.strategy)
        await self.notifier.send(f"🔴 Closed {pos.symbol} | {reason} | PnL: ₹{pnl:+.2f}")

    async def _squareoff_mis(self) -> None:
        """Close every intraday (MIS) position once the 3:14 PM IST cut-off passes.

        Live: the broker-side squareoff sends the closing orders, then the
        positions are dropped from the risk book without sending a second
        order (which would open a new position the other way). Paper: the
        executor has nothing to close at the broker, so each tracked position
        is closed through a simulated fill."""
        logger.info("MIS squareoff triggered at 3:14 PM IST — closing all intraday positions")
        if self.mode == "live":
            await self.executor.squareoff_all_mis()
        if not self._is_intraday_product():
            return
        for pos_list in list(self.risk_manager.positions.values()):
            for pos in list(pos_list):
                price = self._last_price.get(pos.symbol, pos.entry_price)
                await self._close_tracked(pos, price, "mis_squareoff",
                                          send_order=self.mode != "live")

    # ── Position state persistence ─────────────────────────────────────────────

    def _save_state(self, force: bool = False) -> None:
        """Write open positions to data/live_positions.json after any open or
        close, and at least every few seconds (the dashboard's heartbeat).
        Written atomically so a crash mid-write never leaves a corrupt file."""
        import json
        from utils.timeutils import now_ist
        rm = self.risk_manager
        changed = rm.version != self._state_saved_version
        if not (force or changed or time.time() - self._state_saved_at >= _STATE_HEARTBEAT_SEC):
            return
        product = self.executor._default_product.value
        positions = []
        for row in rm.to_state()["positions"]:
            price = self._last_price.get(row["symbol"], row["entry_price"])
            positions.append({
                **row,
                "product": product,
                "current_price": price,
                "unrealised_pnl": (price - row["entry_price"]) * row["direction"] * row["size"],
            })
        exposure = sum(p["entry_price"] * p["size"] for p in positions)
        state = {
            "source": "main",
            "mode": self.mode,
            "saved_at": time.time(),
            "session_date": now_ist().date().isoformat(),
            "initial_capital": rm.initial_capital,
            "capital": rm.capital,
            "cash": rm.capital - exposure,
            "daily_pnl": rm.daily_pnl,
            "daily_trade_count": rm.daily_trade_count,
            "positions": positions,
        }
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._state_file.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(self._state_file)
            self._state_saved_version = rm.version
            self._state_saved_at = state["saved_at"]
        except OSError as exc:
            logger.error(f"Could not save position state: {exc}")

    def _restore_state(self) -> int:
        """Reload open positions after a crash or restart. Returns how many
        were restored.

        Only a file written by this bot in the same mode is used (never
        paper_trade.py's file, never paper positions into live). Intraday
        (MIS) positions from an earlier session are dropped — the broker
        squared them off at 15:20 that day."""
        import json
        from utils.timeutils import now_ist
        if not self._state_file.exists():
            return 0
        try:
            state = json.loads(self._state_file.read_text())
        except (OSError, ValueError) as exc:
            logger.error(f"Could not read position state {self._state_file}: {exc}")
            return 0
        if state.get("source") != "main" or state.get("mode") != self.mode:
            logger.info(f"Ignoring {self._state_file.name}: written by "
                        f"{state.get('source', 'paper_trade.py')} in {state.get('mode', '?')} mode")
            return 0

        same_session = state.get("session_date") == now_ist().date().isoformat()
        keep, dropped = [], []
        for row in state.get("positions", []):
            if row.get("product") == "MIS" and not same_session:
                dropped.append(row["symbol"])
            else:
                keep.append(row)
        if dropped:
            logger.warning(f"Not restoring intraday positions from {state.get('session_date')} "
                           f"(squared off by the broker): {', '.join(dropped)}")

        rm = self.risk_manager
        rm.capital = float(state.get("capital", rm.capital))
        if same_session:
            rm.daily_pnl = float(state.get("daily_pnl", 0.0))
            rm.daily_trade_count = int(state.get("daily_trade_count", 0))
        restored = rm.restore_positions(keep)
        if restored:
            logger.warning(f"Restored {restored} open position(s) from {self._state_file.name}: "
                           + ", ".join(f"{r['symbol']} x{r['size']:g}" for r in keep))
        return restored

    # ── Broker reconciliation (live) ───────────────────────────────────────────

    async def _reconcile_loop(self) -> None:
        interval = self.cfg.get("execution", {}).get("reconcile_interval_sec", 300)
        while True:
            await asyncio.sleep(interval)
            await self._reconcile()

    async def _reconcile(self, at_startup: bool = False) -> None:
        """Compare the bot's book with Upstox and fix positions the broker
        does not back.

        A position the broker does not hold is shrunk to what the broker has
        (no order is sent). At startup that happens immediately; during the
        session it needs two checks in a row, so an order still being filled
        is not mistaken for a missing position. Positions opened today at the
        broker that the bot does not track are only alerted, once per day."""
        from execution_engine.reconcile import compare_books
        from utils.timeutils import now_ist
        try:
            broker_total, broker_today = await self.executor.fetch_broker_quantities()
        except Exception as exc:
            logger.warning(f"Reconciliation skipped — could not read Upstox positions: {exc}")
            return

        rm = self.risk_manager
        expected: dict[str, float] = {}
        key_to_symbol: dict[str, str] = {}
        for symbol, pos_list in rm.positions.items():
            key = self.executor._resolve_key(symbol)
            if not key or not pos_list:
                continue
            key_to_symbol[key] = symbol
            expected[key] = expected.get(key, 0.0) + sum(p.direction * p.size for p in pos_list)

        mismatches = compare_books(expected, broker_total, broker_today)
        missing_keys = {m.key for m in mismatches if m.kind == "missing_at_broker"}
        for key in list(self._recon_strikes):
            if key not in missing_keys:
                del self._recon_strikes[key]   # resolved (e.g. the order finished filling)

        today = now_ist().date()
        for m in mismatches:
            if m.kind == "untracked_at_broker":
                if (today, m.key) not in self._recon_alerted:
                    self._recon_alerted.add((today, m.key))
                    msg = (f"⚠️ Upstox has a position the bot is not tracking: "
                           f"{m.key} qty {m.broker_qty:+d}")
                    logger.warning(msg)
                    await self.notifier.send(msg)
                continue

            symbol = key_to_symbol[m.key]
            self._recon_strikes[m.key] = self._recon_strikes.get(m.key, 0) + 1
            if not at_startup and self._recon_strikes[m.key] < 2:
                logger.warning(f"Reconciliation: {symbol} bot={m.bot_qty:+g} broker={m.broker_qty:+d} "
                               "— will correct if still different on the next check")
                continue
            self._shrink_to_broker(symbol, m.broker_cover)
            del self._recon_strikes[m.key]
            msg = (f"🛑 {symbol}: bot thought it held {m.bot_qty:+g}, Upstox has {m.broker_qty:+d}. "
                   f"Bot position reduced to {m.broker_cover:g}; no order sent. Check the account.")
            logger.error(msg)
            await self.notifier.send(msg)

    def _shrink_to_broker(self, symbol: str, cover: float) -> None:
        """Reduce the bot's positions in `symbol` to the size the broker backs,
        dropping the newest first. P&L for the removed part is booked at the
        last seen price, since the actual exit is unknown."""
        rm = self.risk_manager
        price = self._last_price.get(symbol)
        remaining = cover
        for pos in list(rm.positions.get(symbol, [])):   # oldest first: keep these
            if remaining >= pos.size:
                remaining -= pos.size
            elif remaining > 0:
                pos.size = remaining
                remaining = 0
                rm.version += 1
            else:
                rm.close_position(pos, price if price is not None else pos.entry_price,
                                  "reconcile_missing_at_broker")

    async def _on_tick(self, event: dict) -> None:
        try:
            await self._process_tick(event)
        finally:
            self._save_state()

    def _is_sane_tick(self, symbol: str, price: float) -> bool:
        """Reject corrupt ticks before they reach stops or strategies.

        A price ≤ 0, or a jump of more than execution.max_tick_jump_pct
        (default 20%, the widest NSE circuit band) from the last accepted
        price, is dropped. If the next ticks keep agreeing on the new level
        (3 in a row within 1% of each other) it is real — e.g. a split
        re-basing the feed — and is accepted."""
        if price <= 0:
            return False
        last = self._last_price.get(symbol)
        if not last:
            return True
        limit = self.cfg.get("execution", {}).get("max_tick_jump_pct", 0.20)
        if abs(price - last) / last <= limit:
            self._suspect_ticks.pop(symbol, None)
            return True
        run = self._suspect_ticks.setdefault(symbol, [])
        if run and abs(price - run[-1]) / run[-1] > 0.01:
            run.clear()   # the bad prices don't agree with each other either
        run.append(price)
        if len(run) >= 3:
            logger.warning(f"{symbol}: accepting new price level {price:.2f} "
                           f"(was {last:.2f}) after {len(run)} consistent ticks")
            self._suspect_ticks.pop(symbol, None)
            return True
        logger.warning(f"{symbol}: dropped suspicious tick {price:.2f} "
                       f"({(price - last) / last:+.1%} vs last {last:.2f})")
        return False

    async def _process_tick(self, event: dict) -> None:
        from utils.timeutils import is_mis_squareoff_time, now_ist
        symbol = event.get("symbol", "")
        price  = float(event.get("close", event.get("ltp", 0)))
        if not self._is_sane_tick(symbol, price):
            return
        self._last_price[symbol] = price

        # MIS squareoff at 3:14 PM IST — once per trading day
        ist_now = now_ist()
        past_cutoff = is_mis_squareoff_time(ist_now)
        if past_cutoff and self._mis_squareoff_date != ist_now.date():
            self._mis_squareoff_date = ist_now.date()
            await self._squareoff_mis()

        self.portfolio.update_price(symbol, price)

        # Check stops on every tick
        to_close = self.risk_manager.update_all({symbol: price})
        for pos, reason in to_close:
            await self._close_tracked(pos, price, reason)

        # Generate strategy signals on real candle close, not a tick-count
        # guess — docs/intraday_gaps.md §1. For symbols with an intraday
        # base (equity symbols seeded in _load_historical_data), feed the
        # live bar aggregator and only re-score once a full intraday_tf
        # bar has actually finalized, using freshly-merged live data.
        intraday_key = f"{symbol}_{self.intraday_tf}"
        has_intraday_base = intraday_key in self._df_cache_base
        if has_intraday_base:
            bar_closed = self._live_bars.update(event)
            if not bar_closed:
                return
            self._tick_counter[symbol] = self._tick_counter.get(symbol, 0) + 1
            from data_engine.live_bars import timeframe_minutes
            if self._tick_counter[symbol] % timeframe_minutes(self.intraday_tf) != 0:
                return
            self._refresh_live_df(symbol)
            df = self._df_cache.get(intraday_key)
        else:
            # No intraday base for this symbol (e.g. an index, or an
            # equity beyond the first 5 seeded — see _load_historical_data)
            # — unchanged fallback: score against the daily cache.
            df = self._df_cache.get(symbol)

        if df is None or len(df) < 60:
            return

        # No new intraday entries after the squareoff cut-off: the broker
        # would force-close them minutes later.
        if past_cutoff and self._is_intraday_product():
            return

        signals = self.meta_engine.generate_signals(symbol, df)
        if not signals:
            return

        best = max(signals, key=lambda s: s.confidence)
        from strategies.base import SignalType
        if best.signal_type not in (SignalType.BUY, SignalType.SELL):
            return

        if not await self._handle_existing_position(best, price):
            return

        others = [s for s, lst in self.risk_manager.positions.items() if lst and s != symbol]
        if self.portfolio.is_correlated(symbol, others):
            return

        order = await self.executor.execute_signal(best)
        if order and order.status == "complete":
            await self.notifier.send(
                f"🟢 {best.signal_type.value} {symbol} @ ₹{best.price:.2f} "
                f"| {best.strategy} | conf={best.confidence:.0%}"
            )

    async def _handle_existing_position(self, signal, price: float) -> bool:
        """Apply a signal to any position already open in its symbol.
        Returns True only when the symbol is flat and a new entry may be placed.

        Same direction → ignored (no pyramiding). Opposite direction → the
        open position is closed and the bot stays flat rather than flipping."""
        open_pos = self.risk_manager.positions.get(signal.symbol, [])
        if not open_pos:
            return True
        if any(p.direction != signal.direction for p in open_pos):
            for pos in list(open_pos):
                await self._close_tracked(pos, price, "signal_reversal")
        return False

    async def _on_fill(self, order) -> None:
        from utils.trade_logger import TradeLogger
        self.trade_logger._append({
            "ts": order.created_at,
            "type": "order",
            "symbol": order.instrument_key.split("|")[-1],
            "side": order.transaction_type,
            "quantity": order.quantity,
            "price": order.avg_price,
            "product": order.product.value,
            "strategy": order.tag,
        })

    # ── Paper simulation ────────────────────────────────────────────────────────

    async def _run_paper_simulation(self) -> None:
        """Replay cached daily bars through the strategy engine (paper mode)."""
        from strategies.base import SignalType
        logger.info("Running paper simulation on cached historical data...")
        for symbol, df in self._df_cache.items():
            if "_" in symbol and symbol.count("_") > 1:
                continue  # skip intraday cache keys
            if len(df) < 60:
                continue
            signals = self.meta_engine.generate_signals(symbol, df)
            if signals:
                best = max(signals, key=lambda s: s.confidence)
                if (best.signal_type in (SignalType.BUY, SignalType.SELL)
                        and await self._handle_existing_position(best, best.price)):
                    await self.executor.execute_signal(best)
        self._save_state(force=True)
        metrics = self.portfolio.metrics()
        logger.info(f"Paper simulation metrics: {metrics}")

    async def stop(self) -> None:
        if self._recon_task:
            self._recon_task.cancel()
        await self.feed.stop()
        self._save_state(force=True)
        logger.info("Bot stopped")


# ── Crypto Bot (Binance secondary) ─────────────────────────────────────────────

class CryptoBotAddon:
    """Thin wrapper that adds Binance crypto trading alongside the Upstox bot."""

    def __init__(self, cfg: dict, risk_manager, portfolio, meta_engine,
                 executor, trade_logger):
        from data_engine import MarketDataEngine

        self.cfg = cfg
        self.data_engine = MarketDataEngine(cfg)
        self.symbols: list[str] = cfg.get("assets", {}).get("crypto", [])
        self.primary_tf = cfg.get("timeframes", {}).get("primary", "1h")

        ex_cfg = cfg.get("exchanges", {}).get("binance", {})
        if ex_cfg.get("api_key"):
            self.data_engine.init_exchange(
                "binance",
                api_key=ex_cfg["api_key"],
                api_secret=ex_cfg["api_secret"],
                sandbox=ex_cfg.get("sandbox", True),
            )
        self._risk_manager = risk_manager
        self._portfolio    = portfolio
        self._meta_engine  = meta_engine
        self._executor     = executor
        self._trade_logger = trade_logger
        self._df_cache: dict = {}
        self.data_engine.subscribe(self._on_candle)

    async def load_data(self) -> None:
        for sym in self.symbols:
            df = self.data_engine.fetch_ohlcv(sym, self.primary_tf)
            if not df.empty:
                self._df_cache[sym] = df

    async def start(self) -> None:
        await self.load_data()
        await self.data_engine.start_streaming(self.symbols, "1m")

    async def _on_candle(self, event: dict) -> None:
        from strategies.base import SignalType
        symbol = event["symbol"]
        price  = float(event["close"])
        df = self._df_cache.get(symbol)
        if df is None or len(df) < 60:
            return
        signals = self._meta_engine.generate_signals(symbol, df)
        if not signals:
            return
        best = max(signals, key=lambda s: s.confidence)
        if best.signal_type in (SignalType.BUY, SignalType.SELL):
            await self._executor.execute_signal(best)


# ── Backtesting ────────────────────────────────────────────────────────────────

def run_backtest(cfg: dict, market: str = "india") -> None:
    from backtester import Backtester
    from strategies.meta_engine import MetaStrategyEngine

    engine = MetaStrategyEngine(cfg)
    backtester = Backtester(cfg, initial_capital=cfg.get("portfolio", {}).get("initial_capital", 500_000))

    if market == "india":
        from data_engine.upstox import UpstoxAuth, InstrumentRegistry, UpstoxDataEngine

        up_cfg = cfg.get("exchanges", {}).get("upstox", {})
        auth = UpstoxAuth(
            api_key=up_cfg.get("api_key", ""),
            api_secret=up_cfg.get("api_secret", ""),
            redirect_uri=up_cfg.get("redirect_uri", "http://localhost:3561/callback"),
        )
        auth.load_token()
        registry = InstrumentRegistry()
        registry.load()
        data_engine = UpstoxDataEngine(auth, registry)
        symbols = (cfg.get("assets", {}).get("india_equity", []) +
                   cfg.get("assets", {}).get("india_indices", []))
        tf = cfg.get("timeframes", {}).get("primary", "1d")
    else:
        from data_engine import MarketDataEngine
        data_engine = MarketDataEngine(cfg)
        ex_cfg = cfg.get("exchanges", {}).get("binance", {})
        if ex_cfg.get("api_key"):
            data_engine.init_exchange("binance", ex_cfg["api_key"], ex_cfg["api_secret"])
        symbols = cfg.get("assets", {}).get("crypto", ["BTC/USDT"])
        tf = "1h"

    print(f"\nBacktest — {market.upper()} market | {len(symbols)} symbols | timeframe={tf}")
    print("=" * 70)
    for sym in symbols:
        df = data_engine.fetch_ohlcv(sym, tf)
        if df is None or (hasattr(df, 'empty') and df.empty) or len(df) < 100:
            logger.warning(f"Insufficient data for {sym}")
            continue
        result = backtester.run(df, sym, engine=engine)
        print(result.summary())
    print("=" * 70)


# ── ML training ────────────────────────────────────────────────────────────────

def run_training(cfg: dict) -> None:
    from ml_models import ModelTrainer
    from data_engine.upstox import UpstoxAuth, InstrumentRegistry, UpstoxDataEngine

    up_cfg = cfg.get("exchanges", {}).get("upstox", {})
    auth = UpstoxAuth(
        api_key=up_cfg.get("api_key", ""),
        api_secret=up_cfg.get("api_secret", ""),
        redirect_uri=up_cfg.get("redirect_uri", ""),
    )
    auth.load_token()
    registry = InstrumentRegistry()
    registry.load()
    data_engine = UpstoxDataEngine(auth, registry)
    trainer = ModelTrainer(cfg)

    symbols = cfg.get("assets", {}).get("india_equity", ["RELIANCE"])
    lookback = cfg.get("ml", {}).get("train_lookback_days", 365)

    for sym in symbols[:3]:   # train on top 3 liquid stocks
        df = data_engine.fetch_ohlcv(sym, "1d", lookback_days=lookback)
        if df is not None and len(df) > 300:
            logger.info(f"Training on {sym} ({len(df)} bars)...")
            ensemble = trainer.train_all(df)
            if ensemble:
                logger.info(f"  {sym} — done")
                break  # single model trained on most liquid stock is fine


# ── Upstox OAuth flow ──────────────────────────────────────────────────────────

def run_auth(cfg: dict) -> None:
    from data_engine.upstox.auth import UpstoxAuth, UpstoxAuthServer

    up_cfg = cfg.get("exchanges", {}).get("upstox", {})
    auth = UpstoxAuth(
        api_key=up_cfg.get("api_key", ""),
        api_secret=up_cfg.get("api_secret", ""),
        redirect_uri=up_cfg.get("redirect_uri", "http://localhost:3561/callback"),
        token_file=up_cfg.get("token_file", "data/upstox_token.json"),
    )

    existing = auth.load_token()
    if existing:
        print("✅ Valid Upstox token already exists. No re-authentication needed.")
        print(f"   Token age: check {up_cfg.get('token_file', 'data/upstox_token.json')}")
        return

    port = up_cfg.get("auth_port", 3561)
    server = UpstoxAuthServer(auth, port=port)
    token = server.start_and_wait(timeout=300)
    if token:
        print(f"\n✅ Authentication successful! Token saved.")
        print(f"   You can also set UPSTOX_ACCESS_TOKEN={token[:20]}... in .env")
    else:
        print("\n❌ Authentication failed or timed out.")
        print(f"   Open this URL manually: {auth.auth_url()}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Loony Trading Bot — Upstox (India) + Binance (Crypto)"
    )
    parser.add_argument("--mode", choices=["paper", "live", "backtest", "train", "auth"],
                        default=settings.get("system.mode", "paper"))
    parser.add_argument("--market", choices=["india", "crypto"],
                        default="india",
                        help="Market to use for backtest/train")
    args = parser.parse_args()

    cfg = settings.as_dict()

    if args.mode == "auth":
        run_auth(cfg)

    elif args.mode == "backtest":
        run_backtest(cfg, market=args.market)

    elif args.mode == "train":
        run_training(cfg)

    else:
        bot = UpstoxTradingBot(cfg, mode=args.mode)
        try:
            asyncio.run(bot.start())
        except KeyboardInterrupt:
            asyncio.run(bot.stop())
            logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
