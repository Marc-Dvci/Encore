"""Runtime settings, read once from the environment (and a local .env when present)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


@dataclass(frozen=True)
class Config:
    qloo_api_key: Optional[str]
    qloo_base_url: str
    data_dir: Path
    home_file: Path
    ai_provider: str
    gemini_api_key: Optional[str]
    gemini_model: str
    ai_until: Optional[date]
    ai_daily_cap: int
    ai_per_visitor_hourly: int
    qloo_cache_days: int

    @property
    def db_path(self) -> Path:
        return self.data_dir / "encore.db"


def load_config(env_file: Optional[Path] = None) -> Config:
    _load_dotenv(env_file or ROOT / ".env")
    e = os.environ.get
    until = e("ENCORE_AI_UNTIL")
    data_dir = Path(e("ENCORE_DATA_DIR") or ROOT / "var")
    data_dir.mkdir(parents=True, exist_ok=True)
    return Config(
        qloo_api_key=e("QLOO_API_KEY") or None,
        qloo_base_url=(e("QLOO_BASE_URL") or "https://hackathon.api.qloo.com").rstrip("/"),
        data_dir=data_dir,
        home_file=Path(e("ENCORE_HOME_FILE") or ROOT / "data" / "maple_court.json"),
        ai_provider=e("ENCORE_AI_PROVIDER") or "gemini",
        gemini_api_key=e("GEMINI_API_KEY") or None,
        gemini_model=e("ENCORE_GEMINI_MODEL") or "gemini-3.7-flash",
        ai_until=date.fromisoformat(until) if until else None,
        ai_daily_cap=int(e("ENCORE_AI_DAILY_CAP") or 600),
        ai_per_visitor_hourly=int(e("ENCORE_AI_PER_VISITOR_HOURLY") or 40),
        qloo_cache_days=int(e("ENCORE_QLOO_CACHE_DAYS") or 30),
    )
