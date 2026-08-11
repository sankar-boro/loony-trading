"""
Composite multi-factor signal scoring (MarketPulse AI Phase 2).

Blends seven 0-100 factors into one score per stock, weighted per
config/settings.yaml `signal_engine.weights` (spec §17 defaults: Catalyst
25% / Technical 20% / Momentum 15% / Volume 15% / Historical 10% /
Regime 10% / Risk 5%).

Technical comes from strategies/meta_engine.py — the existing strategy
suite, unchanged, just persisted here. Historical comes from
signals.historical.find_analogues() against real (or clearly-labeled
demo) HistoricalEvent rows — win-rate at the 1d horizon when there are
enough samples to mean anything (>= _HISTORICAL_MIN_SAMPLES), else a flat
neutral 50 rather than a noisy score off 1-2 data points. Entry/stop/
target reuse whatever ATR-based stop the winning strategy signal already
computed (strategies/base.py `_atr_stops`) rather than recomputing risk
logic.

Most stocks should score NO_SIGNAL — see spec §18/§62 ("optimize for
high-quality, explainable opportunities", not signal volume). BULLISH/
BEARISH requires both a fired technical strategy AND score/confidence
above the quality gate; below that but still non-trivial is WATCH.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pandas as pd
from sqlalchemy.orm import Session

from db.models import (
    NewsEvent, Signal as SignalModel, SignalDirection, Stock, StockEvent,
    TradeSetup,
)
from feature_engine.indicators import TechnicalIndicators as TI
from signals.historical import find_analogues
from strategies.base import Signal as StrategySignal, SignalType
from strategies.meta_engine import MetaStrategyEngine
from strategies.regime_detector import MarketRegime, RegimeDetector
from utils.logger import get_logger

logger = get_logger("signal_engine")

_DEFAULT_WEIGHTS = {
    "catalyst": 0.25, "technical": 0.20, "momentum": 0.15, "volume": 0.15,
    "historical": 0.10, "regime": 0.10, "risk": 0.05,
}
_DEFAULT_GATE = {"min_score": 70, "min_confidence": 65, "watch_score": 50}
_HISTORICAL_NEUTRAL = 50.0
_HISTORICAL_MIN_SAMPLES = 5
_CATALYST_LOOKBACK = timedelta(days=3)


@dataclass
class ScoredSignal:
    symbol: str
    direction: SignalDirection
    score: float
    confidence: float
    components: dict[str, float]
    strategy_signal: StrategySignal | None = None
    entry_low: float | None = None
    entry_high: float | None = None
    stop_loss: float | None = None
    target_1: float | None = None
    target_2: float | None = None
    risk_reward: float | None = None


class CompositeSignalEngine:
    def __init__(self, cfg: dict, meta_engine: MetaStrategyEngine | None = None):
        self.cfg = cfg
        se_cfg = cfg.get("signal_engine", {})
        self.weights = {**_DEFAULT_WEIGHTS, **se_cfg.get("weights", {})}
        self.gate = {**_DEFAULT_GATE, **se_cfg.get("quality_gate", {})}
        self.meta_engine = meta_engine or MetaStrategyEngine(cfg)
        self.regime_detector = RegimeDetector(cfg)

    # ── public API ────────────────────────────────────────────────────────────

    def score_symbol(self, db: Session, symbol: str, df: pd.DataFrame) -> ScoredSignal:
        strategy_signals = self.meta_engine.generate_signals(symbol, df)
        best = self.meta_engine.best_signal(strategy_signals)

        technical_score, direction_hint = self._technical_component(best)
        momentum_score = self._momentum_component(df)
        volume_score = self._volume_component(df)
        catalyst_score, catalyst_dir, catalyst_event_type = self._catalyst_component(db, symbol)
        regime_score = self._regime_component(df, symbol, direction_hint)
        risk_score = self._risk_component(df)
        historical_score = self._historical_component(db, catalyst_event_type, catalyst_dir)

        components = {
            "catalyst": round(catalyst_score, 1),
            "technical": round(technical_score, 1),
            "momentum": round(momentum_score, 1),
            "volume": round(volume_score, 1),
            "historical": round(historical_score, 1),
            "regime": round(regime_score, 1),
            "risk": round(risk_score, 1),
        }
        total = sum(components[k] * self.weights[k] for k in components)
        direction, confidence = self._classify(best, total, direction_hint)

        scored = ScoredSignal(
            symbol=symbol, direction=direction, score=round(total, 1),
            confidence=round(confidence, 1), components=components,
            strategy_signal=best,
        )
        if direction in (SignalDirection.BULLISH, SignalDirection.BEARISH) and best is not None:
            self._attach_trade_setup(scored, best, df)
        return scored

    def persist(self, db: Session, scored: ScoredSignal) -> SignalModel | None:
        stock = db.query(Stock).filter(Stock.symbol == scored.symbol).first()
        if not stock:
            logger.warning(f"Skipping persist for unknown stock: {scored.symbol}")
            return None

        signal = SignalModel(
            stock_id=stock.id,
            direction=scored.direction,
            score=scored.score,
            confidence=scored.confidence,
            catalyst_score=scored.components["catalyst"],
            technical_score=scored.components["technical"],
            momentum_score=scored.components["momentum"],
            volume_score=scored.components["volume"],
            historical_score=scored.components["historical"],
            regime_score=scored.components["regime"],
            risk_score=scored.components["risk"],
            explanation=scored.components,
        )
        db.add(signal)
        db.flush()

        if scored.stop_loss is not None:
            db.add(TradeSetup(
                signal_id=signal.id,
                entry_low=scored.entry_low, entry_high=scored.entry_high,
                stop_loss=scored.stop_loss, target_1=scored.target_1,
                target_2=scored.target_2, risk_reward=scored.risk_reward,
            ))
        return signal

    # ── components ───────────────────────────────────────────────────────────

    @staticmethod
    def _technical_component(best: StrategySignal | None) -> tuple[float, int]:
        if best is None:
            return 0.0, 0
        direction = 1 if best.signal_type == SignalType.BUY else -1
        # Strategy confidence is documented as 0-1 but isn't universally
        # enforced at the source — clamp so a misbehaving strategy can't
        # push the composite score or displayed confidence above 100.
        confidence_pct = max(0.0, min(100.0, float(best.confidence) * 100))
        return confidence_pct, direction

    @staticmethod
    def _momentum_component(df: pd.DataFrame) -> float:
        if df is None or len(df) < 15 or "close" not in df:
            return 0.0
        rsi = TI.rsi(df["close"]).iloc[-1]
        if pd.isna(rsi):
            return 0.0
        rsi = float(rsi)
        return min(abs(rsi - 50) / 50 * 100, 100.0)

    @staticmethod
    def _volume_component(df: pd.DataFrame) -> float:
        if df is None or len(df) < 20 or "volume" not in df:
            return 0.0
        avg_vol = float(df["volume"].tail(20).mean())
        if not avg_vol:
            return 0.0
        rel_vol = float(df["volume"].iloc[-1]) / avg_vol
        return max(0.0, min(100.0, (rel_vol - 1.0) * 50 + 50))

    @staticmethod
    def _catalyst_component(db: Session, symbol: str) -> tuple[float, str | None, str | None]:
        stock = db.query(Stock).filter(Stock.symbol == symbol).first()
        if not stock:
            return 0.0, None, None

        since = datetime.now(timezone.utc) - _CATALYST_LOOKBACK
        row = (
            db.query(StockEvent, NewsEvent)
            .join(NewsEvent, StockEvent.event_id == NewsEvent.id)
            .filter(StockEvent.stock_id == stock.id, StockEvent.created_at >= since)
            .order_by((StockEvent.relevance_score * NewsEvent.catalyst_score).desc())
            .first()
        )
        if not row:
            return 0.0, None, None
        stock_event, news_event = row
        score = news_event.catalyst_score * 10 * stock_event.relevance_score
        return score, stock_event.direction, news_event.event_type

    @staticmethod
    def _historical_component(db: Session, event_type: str | None, direction: str | None) -> float:
        """Real analogue win-rate when there's a live catalyst and enough
        matured history to say something meaningful; flat neutral otherwise
        — spec §22 explicitly wants this labeled analysis, not a forecast,
        and a 2-sample "100% win rate" would read as exactly that."""
        if not event_type:
            return _HISTORICAL_NEUTRAL
        result = find_analogues(db, event_type=event_type, direction=direction)
        day_1 = next((h for h in result.horizons if h.horizon == "1d"), None)
        if not day_1 or day_1.sample_count < _HISTORICAL_MIN_SAMPLES or day_1.win_rate_pct is None:
            return _HISTORICAL_NEUTRAL
        return day_1.win_rate_pct

    def _regime_component(self, df: pd.DataFrame, symbol: str, direction_hint: int) -> float:
        if df is None or len(df) < 30:
            return 50.0
        try:
            regime = self.regime_detector.detect(df, symbol=symbol)
        except Exception as e:
            logger.debug(f"Regime detection failed for {symbol}: {e}")
            return 50.0

        if direction_hint == 0:
            return 50.0
        if regime == MarketRegime.TRENDING_UP:
            return 80.0 if direction_hint > 0 else 20.0
        if regime == MarketRegime.TRENDING_DOWN:
            return 80.0 if direction_hint < 0 else 20.0
        if regime == MarketRegime.HIGH_VOLATILITY:
            return 35.0
        if regime == MarketRegime.LOW_VOLATILITY:
            return 55.0
        return 60.0  # RANGING — favorable for the mean-reversion strategies likely firing

    @staticmethod
    def _risk_component(df: pd.DataFrame) -> float:
        if df is None or len(df) < 15:
            return 50.0
        atr = TI.atr(df, 14).iloc[-1]
        close = df["close"].iloc[-1]
        if pd.isna(atr) or not close:
            return 50.0
        atr_pct = float(atr) / float(close)
        return max(0.0, min(100.0, 100.0 - atr_pct * 1500))

    # ── classification & trade setup ────────────────────────────────────────

    def _classify(
        self, best: StrategySignal | None, total: float, direction_hint: int,
    ) -> tuple[SignalDirection, float]:
        if best is None:
            return SignalDirection.NO_SIGNAL, 0.0

        confidence = max(0.0, min(100.0, float(best.confidence) * 100))
        if total >= self.gate["min_score"] and confidence >= self.gate["min_confidence"]:
            direction = SignalDirection.BULLISH if direction_hint > 0 else SignalDirection.BEARISH
        elif total >= self.gate["watch_score"]:
            direction = SignalDirection.WATCH
        else:
            direction = SignalDirection.NO_SIGNAL
        return direction, confidence

    @staticmethod
    def _attach_trade_setup(scored: ScoredSignal, best: StrategySignal, df: pd.DataFrame) -> None:
        atr = TI.atr(df, 14).iloc[-1]
        atr = 0.0 if pd.isna(atr) else float(atr)
        price = float(best.price)
        band = atr * 0.15

        scored.entry_low = round(price - band, 2)
        scored.entry_high = round(price + band, 2)
        scored.stop_loss = round(float(best.stop_loss), 2)
        scored.target_1 = round(float(best.take_profit), 2)
        scored.target_2 = round(price + (float(best.take_profit) - price) * 1.5, 2)

        risk = abs(price - float(best.stop_loss))
        reward = abs(float(best.take_profit) - price)
        scored.risk_reward = round(reward / risk, 2) if risk > 0 else None
