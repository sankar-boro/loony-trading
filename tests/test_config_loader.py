"""config.loader reads .env so ${VAR} values resolve for every entry point,
including main.py, which loads no .env of its own."""
import os

from config.loader import Settings, load_dotenv


def test_dotenv_fills_missing_but_never_overrides(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nLOONY_TEST_A=from_file  # trailing\nLOONY_TEST_B='quo # ted'\nLOONY_TEST_C=file\n")
    monkeypatch.delenv("LOONY_TEST_A", raising=False)
    monkeypatch.delenv("LOONY_TEST_B", raising=False)
    monkeypatch.setenv("LOONY_TEST_C", "real_env")
    load_dotenv(env)
    assert os.environ["LOONY_TEST_A"] == "from_file"
    assert os.environ["LOONY_TEST_B"] == "quo # ted"
    assert os.environ["LOONY_TEST_C"] == "real_env"
    for k in ("LOONY_TEST_A", "LOONY_TEST_B"):
        monkeypatch.delenv(k)


def test_settings_expands_env_vars(tmp_path, monkeypatch):
    cfg = tmp_path / "s.yaml"
    cfg.write_text('exchanges:\n  upstox:\n    api_key: "${LOONY_TEST_KEY}"\n')
    monkeypatch.setenv("LOONY_TEST_KEY", "abc")
    assert Settings(str(cfg)).get("exchanges.upstox.api_key") == "abc"
