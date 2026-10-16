import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from encore.ai import AI  # noqa: E402
from encore.config import ROOT, Config  # noqa: E402
from encore.qloo import Qloo  # noqa: E402
from encore.service import Encore  # noqa: E402
from encore.store import Store  # noqa: E402
from tests.fake_qloo import FakeQloo  # noqa: E402


def make_config(tmp: Path, **over) -> Config:
    base = dict(qloo_api_key="test-key", qloo_base_url="https://qloo.test", data_dir=tmp,
                home_file=ROOT / "data" / "maple_court.json", ai_provider="none", gemini_api_key=None,
                gemini_model="gemini-test", ai_until=None, ai_daily_cap=10, ai_per_visitor_hourly=5, qloo_cache_days=30)
    base.update(over)
    return Config(**base)


@pytest.fixture
def fake() -> FakeQloo:
    return FakeQloo()


@pytest.fixture
async def enc(tmp_path, fake):
    cfg = make_config(tmp_path)
    store = Store(cfg.db_path)
    qloo = Qloo(cfg, store, transport=fake.transport())
    qloo.min_interval = 0
    e = Encore(cfg, store=store, qloo=qloo, ai=AI(cfg, store.kv_get, store.kv_set))
    await e.start()
    yield e
    await e.aclose()
