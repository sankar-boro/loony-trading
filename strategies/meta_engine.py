from __future__ import annotations
import asyncio
from typing import Dict, List, Optional
import pandas as pd

from strategies.base import BaseStrategy, Signal
from strategies.regime_detector import RegimeDetector, MarketRegime
from strategies.trend import (
    EmaCrossoverStrategy, MultiTimeframeTrendStrategy,
    SupertrendStrategy, DonchianBreakoutStrategy,
)
from strategies.mean_reversion import (
    RsiReversionStrategy, BollingerReversionStrategy,
    ZscoreReversionStrategy, VwapReversionStrategy,
)
from strategies.breakout import (
    SupportResistanceBreakoutStrategy, AtrBreakoutStrategy, RangeBreakoutStrategy,
)
from strategies.momentum import MacdMomentumStrategy, RsiMomentumStrategy, VolumeMomentumStrategy
from strategies.microstructure import OrderBookImbalanceStrategy
from strategies.stat_arb import PairTradingStrategy
from strategies.candlestick import CandlestickPatternStrategy
from strategies.ml_based import MLClassifierStrategy
from utils.logger import get_logger

logger = get_logger("meta_engine")


class MetaStrategyEngine:
    """
    Orchestrates all strategies.
    For each bar:
      1. Detect market regime
      2. Filter strategies by preferred regime
      3. Collect signals from eligible strategies
      4. Score & blend signals using confidence × strategy weight
      5. Return highest-scoring actionable signal per symbol
    """

    def __init__(self, cfg: dict, ml_model=None):
        self.cfg = cfg
        self.regime_detector = RegimeDetector(cfg)
        self.enabled_names = set(cfg.get("strategies", {}).get("enabled", []))

        all_strategies: List[BaseStrategy] = [
            EmaCrossoverStrategy(cfg),
            MultiTimeframeTrendStrategy(cfg),
            SupertrendStrategy(cfg),
            DonchianBreakoutStrategy(cfg),
            RsiReversionStrategy(cfg),
            BollingerReversionStrategy(cfg),
            ZscoreReversionStrategy(cfg),
            VwapReversionStrategy(cfg),
            SupportResistanceBreakoutStrategy(cfg),
            AtrBreakoutStrategy(cfg),
            RangeBreakoutStrategy(cfg),
            MacdMomentumStrategy(cfg),
            RsiMomentumStrategy(cfg),
            VolumeMomentumStrategy(cfg),
            OrderBookImbalanceStrategy(cfg),
            CandlestickPatternStrategy(cfg),
        ]

        ml_strategy = MLClassifierStrategy(cfg, model=ml_model)
        all_strategies.append(ml_strategy)

        self.strategies: List[BaseStrategy] = [
            s for s in all_strategies
            if not self.enabled_names or s.name in self.enabled_names
        ]
        self._pair_strategy = PairTradingStrategy(cfg)
        logger.info(f"MetaEngine loaded {len(self.strategies)} strategies")

    def update_ml_model(self, model) -> None:
        for s in self.strategies:
            if isinstance(s, MLClassifierStrategy):
                s.set_model(model)

    def generate_signals(
        self,
        symbol: str,
        df: pd.DataFrame,
        extra_kwargs: dict | None = None,
    ) -> List[Signal]:
        extra_kwargs = extra_kwargs or {}
        regime = self.regime_detector.detect(df)
        signals = []

        for strategy in self.strategies:
            if not strategy.enabled:
                continue
            if not self.regime_detector.regime_matches(regime, strategy.preferred_regimes):
                continue
            try:
                sig = strategy.generate_signal(df, symbol, **self._filter_kwargs(strategy, extra_kwargs))
                if sig is not None:
                    signals.append(sig)
            except Exception as e:
                logger.warning(f"Strategy {strategy.name} error: {e}")

        return signals

    def best_signal(self, signals: List[Signal]) -> Optional[Signal]:
        """Returns the signal with the highest weighted confidence score."""
        if not signals:
            return None
        weights: dict = self.cfg.get("strategies", {}).get("weights", {})
        return max(signals, key=lambda s: s.confidence * weights.get(s.strategy, 1.0))

    def generate_pair_signals(
        self,
        df_map: Dict[str, pd.DataFrame],
        pairs: List[tuple[str, str]],
    ) -> List[Signal]:
        results = []
        for sym_a, sym_b in pairs:
            if sym_a not in df_map or sym_b not in df_map:
                continue
            s_a, s_b = self._pair_strategy.generate_pair_signals(
                df_map[sym_a], df_map[sym_b], sym_a, sym_b
            )
            if s_a:
                results.append(s_a)
            if s_b:
                results.append(s_b)
        return results

    @staticmethod
    def _filter_kwargs(strategy: BaseStrategy, kwargs: dict) -> dict:
        """Pass only kwargs that the strategy.generate_signal accepts."""
        import inspect
        sig = inspect.signature(strategy.generate_signal)
        valid = set(sig.parameters.keys()) - {"self", "df", "symbol"}
        return {k: v for k, v in kwargs.items() if k in valid}
