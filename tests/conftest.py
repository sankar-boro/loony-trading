"""Keep the offline suite offline.

The project's .env is loaded at import time (config/loader.py, db/base.py),
so without this a test that reaches a notifier or an API client would use
your real credentials — e.g. POST /api/alerts/evaluate builds a real
TelegramAlerter and posts from a background thread.

This runs before any project module is imported. Values set here win over
.env, because load_dotenv() never overrides a variable that is already set.
"""
import os

# Never send notifications or call paid APIs from tests, even if exported.
for _key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "EMAIL_USER",
             "EMAIL_PASSWORD", "EMAIL_TO", "NEWS_API_KEY", "ANTHROPIC_API_KEY"):
    os.environ[_key] = ""
os.environ["LLM_PROVIDER"] = "demo"

# Broker credentials: ignore .env, but keep a token you export on purpose
# (UPSTOX_ACCESS_TOKEN=<token> pytest tests/test_live_upstox.py).
for _key in ("UPSTOX_ACCESS_TOKEN", "UPSTOX_EXTENDED_TOKEN", "UPSTOX_API_KEY", "UPSTOX_API_SECRET"):
    os.environ.setdefault(_key, "")


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _isolated_hmm_models(tmp_path, monkeypatch):
    """HMM regime models go to a temporary directory, never models/hmm/."""
    import strategies.hmm_regime as hmm_regime
    monkeypatch.setattr(hmm_regime, "_MODEL_DIR", tmp_path / "hmm")


def pytest_configure(config):
    # hmmlearn emits a NumPy deprecation warning (and divide warnings on
    # degenerate fits) on every fit; they are not ours
    config.addinivalue_line("filterwarnings", "ignore::DeprecationWarning:hmmlearn.*")
    config.addinivalue_line("filterwarnings", "ignore::RuntimeWarning:hmmlearn.*")
