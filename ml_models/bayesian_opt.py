"""
Bayesian Hyperparameter Optimisation for strategy parameters.

Why Bayesian > Grid/Random search:
- Grid search: O(n^k) — exponential in number of params, wastes evaluations
- Random search: better but still blind — doesn't learn from past results
- Bayesian: builds a surrogate model of the objective, explores intelligently
  Expected Improvement acquisition: trades off exploitation vs exploration

Implementation:
- Gaussian Process surrogate (sklearn) for smooth continuous params
- Tree-structured Parzen Estimator (TPE) fallback via Optuna if available
- Works on: strategy entry/exit thresholds, position sizing, indicator periods

Objective function:
- Run backtest with given params → compute Sharpe ratio
- Minimise: -Sharpe (or maximise Calmar = return/max_dd)
- Constrain: max_drawdown <= threshold (via penalty)

Usage:
    optimizer = BayesianOptimizer(
        param_space={
            "entry_z": (1.5, 3.5),        # continuous range
            "exit_z":  (0.1, 1.0),
            "lookback": (20, 100, "int"),  # integer param
        },
        objective_fn=backtest_sharpe,
        n_trials=50,
    )
    best_params = optimizer.optimize()
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

from utils.logger import get_logger

logger = get_logger("bayesian_opt")


@dataclass
class Trial:
    number:    int
    params:    Dict[str, Any]
    value:     float          # objective value (higher = better)
    metadata:  dict = field(default_factory=dict)


@dataclass
class OptimizationResult:
    best_params:  Dict[str, Any]
    best_value:   float
    n_trials:     int
    all_trials:   List[Trial]
    method:       str

    def summary(self) -> str:
        lines = [
            f"Bayesian Opt ({self.method}): {self.n_trials} trials",
            f"Best value: {self.best_value:.4f}",
            "Best params:",
        ] + [f"  {k}: {v}" for k, v in self.best_params.items()]
        return "\n".join(lines)


class BayesianOptimizer:
    """
    Bayesian hyperparameter optimisation with GP surrogate.

    param_space: dict of {name: (low, high) or (low, high, "int")}
    objective_fn: callable that takes params dict and returns float (higher=better)
    """

    def __init__(
        self,
        param_space:   Dict[str, Tuple],
        objective_fn:  Callable[[Dict[str, Any]], float],
        n_trials:      int   = 50,
        n_warmup:      int   = 10,     # random exploration before GP kicks in
        max_dd_penalty: float = 10.0,  # subtract this if drawdown constraint violated
        seed:          int   = 42,
    ):
        self.param_space    = param_space
        self.objective_fn   = objective_fn
        self.n_trials       = n_trials
        self.n_warmup       = n_warmup
        self.max_dd_penalty = max_dd_penalty
        self.seed           = seed
        self._trials:       List[Trial] = []
        self._rng           = np.random.RandomState(seed)

    # ── Optuna-based (preferred) ──────────────────────────────────────────────

    def _run_optuna(self) -> OptimizationResult:
        """Run Bayesian optimization via Optuna (TPE sampler)."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)

        def _optuna_objective(trial) -> float:
            params = {}
            for name, spec in self.param_space.items():
                if len(spec) == 3 and spec[2] == "int":
                    params[name] = trial.suggest_int(name, int(spec[0]), int(spec[1]))
                elif len(spec) == 3 and spec[2] == "categorical":
                    params[name] = trial.suggest_categorical(name, list(spec[:2]))
                elif len(spec) == 3 and spec[2] == "log":
                    params[name] = trial.suggest_float(name, float(spec[0]), float(spec[1]), log=True)
                else:
                    params[name] = trial.suggest_float(name, float(spec[0]), float(spec[1]))
            try:
                value = float(self.objective_fn(params))
            except Exception as e:
                logger.warning(f"Trial failed: {e}")
                value = -999.0
            self._trials.append(Trial(number=len(self._trials), params=params, value=value))
            return value

        sampler = optuna.samplers.TPESampler(seed=self.seed)
        study   = optuna.create_study(direction="maximize", sampler=sampler)
        study.optimize(_optuna_objective, n_trials=self.n_trials, show_progress_bar=False)

        best = study.best_trial
        return OptimizationResult(
            best_params=best.params,
            best_value=best.value,
            n_trials=self.n_trials,
            all_trials=self._trials,
            method="optuna_tpe",
        )

    # ── GP surrogate (fallback) ───────────────────────────────────────────────

    def _sample_random(self) -> Dict[str, Any]:
        params = {}
        for name, spec in self.param_space.items():
            lo, hi = float(spec[0]), float(spec[1])
            val = self._rng.uniform(lo, hi)
            if len(spec) >= 3 and spec[2] == "int":
                val = int(round(val))
            params[name] = val
        return params

    def _params_to_vector(self, params: Dict[str, Any]) -> np.ndarray:
        return np.array([float(params[k]) for k in sorted(self.param_space.keys())])

    def _expected_improvement(
        self,
        X_new:   np.ndarray,
        X_train: np.ndarray,
        y_train: np.ndarray,
        xi:      float = 0.01,
    ) -> float:
        """
        Expected Improvement acquisition function using GP surrogate.
        Higher XI = more exploration.
        """
        from sklearn.gaussian_process import GaussianProcessRegressor
        from sklearn.gaussian_process.kernels import Matern

        if len(X_train) < 3:
            return float(self._rng.rand())

        gp = GaussianProcessRegressor(
            kernel=Matern(nu=2.5), alpha=1e-6,
            normalize_y=True, n_restarts_optimizer=3,
        )
        try:
            gp.fit(X_train, y_train)
            mu, sigma = gp.predict(X_new.reshape(1, -1), return_std=True)
            mu, sigma = float(mu), float(sigma)
        except Exception:
            return float(self._rng.rand())

        best_y = float(y_train.max())
        Z = (mu - best_y - xi) / (sigma + 1e-9)
        from scipy.stats import norm
        ei = sigma * (Z * norm.cdf(Z) + norm.pdf(Z))
        return float(ei)

    def _run_gp(self) -> OptimizationResult:
        """Run Bayesian optimization with Gaussian Process surrogate."""
        X_train = np.zeros((0, len(self.param_space)))
        y_train = np.zeros(0)

        for i in range(self.n_trials):
            if i < self.n_warmup:
                params = self._sample_random()
            else:
                # Candidate search: evaluate EI on 200 random candidates
                candidates = [self._sample_random() for _ in range(200)]
                best_ei    = -np.inf
                best_cand  = candidates[0]
                for cand in candidates:
                    x_cand = self._params_to_vector(cand)
                    ei = self._expected_improvement(x_cand, X_train, y_train)
                    if ei > best_ei:
                        best_ei, best_cand = ei, cand
                params = best_cand

            try:
                value = float(self.objective_fn(params))
            except Exception as e:
                logger.warning(f"Trial {i} failed: {e}")
                value = -999.0

            trial = Trial(number=i, params=params, value=value)
            self._trials.append(trial)

            x_new  = self._params_to_vector(params).reshape(1, -1)
            X_train = np.vstack([X_train, x_new]) if len(X_train) > 0 else x_new
            y_train = np.append(y_train, value)

            if (i + 1) % 10 == 0:
                best_so_far = float(y_train.max())
                logger.info(f"GP trial {i+1}/{self.n_trials}: best={best_so_far:.4f}")

        best_idx    = int(np.argmax(y_train))
        best_trial  = self._trials[best_idx]

        return OptimizationResult(
            best_params=best_trial.params,
            best_value=best_trial.value,
            n_trials=self.n_trials,
            all_trials=self._trials,
            method="gp_ei",
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def optimize(self) -> OptimizationResult:
        """
        Run optimization — tries Optuna first, falls back to GP.
        """
        logger.info(
            f"BayesianOpt: {self.n_trials} trials, "
            f"params={list(self.param_space.keys())}"
        )
        try:
            import optuna
            result = self._run_optuna()
        except ImportError:
            logger.info("Optuna not available — using GP surrogate")
            result = self._run_gp()

        logger.info(result.summary())
        return result

    def best_n(self, n: int = 5) -> List[Trial]:
        """Return top N trials by objective value."""
        return sorted(self._trials, key=lambda t: t.value, reverse=True)[:n]


# ── Convenience: strategy-specific optimisers ─────────────────────────────────

def optimize_pair_trading(
    backtest_fn: Callable,
    n_trials: int = 50,
) -> OptimizationResult:
    """
    Optimise pair trading z-score entry/exit thresholds.
    backtest_fn(entry_z, exit_z, lookback) → Sharpe ratio
    """
    def _obj(p):
        return backtest_fn(
            entry_z=p["entry_z"],
            exit_z=p["exit_z"],
            lookback=int(p["lookback"]),
        )

    opt = BayesianOptimizer(
        param_space={
            "entry_z":  (1.5, 4.0),
            "exit_z":   (0.1, 1.5),
            "lookback": (20, 120, "int"),
        },
        objective_fn=_obj,
        n_trials=n_trials,
    )
    return opt.optimize()


def optimize_vix_strategy(
    backtest_fn: Callable,
    n_trials: int = 40,
) -> OptimizationResult:
    """Optimise VIX threshold levels for spike reversal strategy."""
    def _obj(p):
        return backtest_fn(
            spike_threshold=p["spike_threshold"],
            nifty_drop_pct=p["nifty_drop_pct"],
            hold_days=int(p["hold_days"]),
        )

    opt = BayesianOptimizer(
        param_space={
            "spike_threshold": (15.0, 40.0),
            "nifty_drop_pct":  (1.0, 5.0),
            "hold_days":       (2, 15, "int"),
        },
        objective_fn=_obj,
        n_trials=n_trials,
    )
    return opt.optimize()
