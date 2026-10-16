import asyncio, sys
sys.path.insert(0, ".")
from encore.config import load_config
from encore.store import Store
from encore.qloo import Qloo
from encore import roster, taste
async def main():
    cfg = load_config(); store = Store(cfg.db_path); q = Qloo(cfg, store)
    roster.load_home(store, cfg.home_file); roster.register_privacy(store, q.guard)
    await roster.resolve_pending(store, q)
    for p in roster.people(store, "resident"):
        prof = await taste.era_profile(store, q, p, limit=6)
        print(f"## {p['first_name']} {p['birth_year']} {p['city']}")
        for d in ("artist", "movie", "tv_show"):
            s = prof["shelves"][d]
            print(f"  {d:<7} n={len(s['items'])} out={s['outside_era']}: " + " | ".join(f"{i['name']} ({i['year']})" for i in s["items"][:5]))
    print("live calls", q.live_calls)
    await q.aclose()
asyncio.run(main())
