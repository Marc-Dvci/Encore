"""Settings come from the environment, with a local .env filling only what the environment leaves unset."""
from datetime import date

import pytest

from encore.config import load_config

KEYS = ("QLOO_API_KEY", "QLOO_BASE_URL", "ENCORE_DATA_DIR", "ENCORE_HOME_FILE", "ENCORE_AI_PROVIDER", "GEMINI_API_KEY",
        "ENCORE_GEMINI_MODEL", "ENCORE_AI_UNTIL", "ENCORE_AI_DAILY_CAP", "ENCORE_AI_PER_VISITOR_HOURLY",
        "ENCORE_QLOO_CACHE_DAYS")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for k in KEYS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ENCORE_DATA_DIR", str(tmp_path / "data"))
    return monkeypatch


def test_defaults_without_any_settings(env, tmp_path):
    cfg = load_config(tmp_path / "missing.env")
    assert cfg.qloo_api_key is None and cfg.gemini_api_key is None
    assert cfg.qloo_base_url == "https://hackathon.api.qloo.com"
    assert (cfg.ai_provider, cfg.gemini_model) == ("gemini", "gemini-3.7-flash")
    assert (cfg.ai_until, cfg.ai_daily_cap, cfg.ai_per_visitor_hourly, cfg.qloo_cache_days) == (None, 600, 40, 30)
    assert cfg.db_path == tmp_path / "data" / "encore.db" and cfg.data_dir.is_dir()


def test_values_are_parsed(env, tmp_path):
    env.setenv("QLOO_BASE_URL", "https://qloo.example/")
    env.setenv("ENCORE_AI_UNTIL", "2026-11-30")
    env.setenv("ENCORE_AI_DAILY_CAP", "7")
    env.setenv("ENCORE_QLOO_CACHE_DAYS", "2")
    cfg = load_config(tmp_path / "missing.env")
    assert cfg.qloo_base_url == "https://qloo.example"
    assert cfg.ai_until == date(2026, 11, 30) and cfg.ai_daily_cap == 7 and cfg.qloo_cache_days == 2


def test_a_dotenv_file_fills_gaps_but_never_overrides_the_environment(env, tmp_path):
    f = tmp_path / ".env"
    f.write_text("# a comment\n\nQLOO_API_KEY = from-file\nGEMINI_API_KEY=from-file\nnot a setting\n", encoding="utf-8")
    env.setenv("GEMINI_API_KEY", "from-environment")
    cfg = load_config(f)
    assert cfg.qloo_api_key == "from-file" and cfg.gemini_api_key == "from-environment"


def test_empty_keys_count_as_unset(env, tmp_path):
    env.setenv("QLOO_API_KEY", "")
    env.setenv("GEMINI_API_KEY", "")
    cfg = load_config(tmp_path / "missing.env")
    assert cfg.qloo_api_key is None and cfg.gemini_api_key is None
