import numpy as np
import pandas as pd
from pathlib import Path
from typing import Optional
from utils.logger import get_logger

logger = get_logger("rl_agent")


class TradingEnvironment:
    """
    Custom Gym-compatible trading environment for RL.
    State: window of features + current position.
    Action: 0=hold, 1=buy, 2=sell/close.
    Reward: risk-adjusted return (Sharpe-like).
    """

    def __init__(self, df: pd.DataFrame, feature_cols: list[str],
                 initial_capital: float = 10_000,
                 window: int = 20, commission: float = 0.001):
        self.df = df.reset_index(drop=True)
        self.feature_cols = feature_cols
        self.initial_capital = initial_capital
        self.window = window
        self.commission = commission
        self.reset()

    @property
    def observation_space_shape(self):
        return (self.window * len(self.feature_cols) + 2,)

    @property
    def action_space_n(self):
        return 3

    def reset(self):
        self.current_step = self.window
        self.capital = self.initial_capital
        self.position = 0
        self.entry_price = 0.0
        self.equity_curve = [self.initial_capital]
        return self._obs()

    def _obs(self):
        features = self.df[self.feature_cols].iloc[
            self.current_step - self.window:self.current_step
        ].values.flatten()
        return np.concatenate([features, [self.position, self.capital / self.initial_capital]])

    def step(self, action: int):
        price = self.df["close"].iloc[self.current_step]
        reward = 0.0

        if action == 1 and self.position == 0:  # buy
            self.position = self.capital / price * (1 - self.commission)
            self.entry_price = price
            self.capital = 0

        elif action == 2 and self.position > 0:  # close long
            pnl = self.position * (price - self.entry_price) - self.commission * self.position * price
            self.capital = self.position * price * (1 - self.commission)
            reward = pnl / self.initial_capital
            self.position = 0

        # mark-to-market
        equity = self.capital + (self.position * price if self.position > 0 else 0)
        self.equity_curve.append(equity)

        self.current_step += 1
        done = self.current_step >= len(self.df) - 1
        return self._obs(), reward, done, {}


class RLTradingAgent:
    """
    PPO-based RL agent using stable-baselines3.
    Falls back gracefully if sb3 is not installed.
    """

    def __init__(self, cfg: dict):
        self.cfg = cfg.get("ml", {}).get("reinforcement", {})
        self.total_timesteps = self.cfg.get("total_timesteps", 100_000)
        self.model_path = Path("models/rl_agent")
        self.model = None
        self.is_trained = False

    def train(self, df: pd.DataFrame, feature_cols: list[str]) -> None:
        if not self.cfg.get("enabled", False):
            logger.info("RL agent disabled in config")
            return
        try:
            from stable_baselines3 import PPO
            from stable_baselines3.common.vec_env import DummyVecEnv
            import gymnasium as gym
        except ImportError:
            logger.error("stable-baselines3 / gymnasium not installed")
            return

        env = TradingEnvironment(df, feature_cols)
        vec_env = DummyVecEnv([lambda: _GymWrapper(env)])
        self.model = PPO("MlpPolicy", vec_env, verbose=0)
        self.model.learn(total_timesteps=self.total_timesteps)
        self.model.save(str(self.model_path))
        self.is_trained = True
        logger.info("RL agent trained and saved")

    def predict(self, obs: np.ndarray) -> int:
        if not self.is_trained or self.model is None:
            return 0
        action, _ = self.model.predict(obs, deterministic=True)
        return int(action)

    def load(self) -> bool:
        try:
            from stable_baselines3 import PPO
            self.model = PPO.load(str(self.model_path))
            self.is_trained = True
            return True
        except Exception:
            return False


class _GymWrapper:
    """Minimal gymnasium wrapper around TradingEnvironment."""
    def __init__(self, env: TradingEnvironment):
        self.env = env
        import gymnasium as gym
        obs_shape = env.observation_space_shape
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf, shape=obs_shape, dtype=np.float32
        )
        self.action_space = gym.spaces.Discrete(env.action_space_n)

    def reset(self, **kwargs):
        obs = self.env.reset()
        return obs.astype(np.float32), {}

    def step(self, action):
        obs, reward, done, info = self.env.step(int(action))
        return obs.astype(np.float32), reward, done, False, info
