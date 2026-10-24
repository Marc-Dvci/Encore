import asyncio
import sys
sys.path.insert(0, ".")
from encore.config import load_config
from encore.store import Store
from encore.qloo import Qloo
from encore import roster, taste

async def main(pid):
    cfg = load_config()
    store = Store(cfg.db_path)
    q = Qloo(cfg, store)
    roster.load_home(store, cfg.home_file)
    roster.register_privacy(store, q.guard)
    print(await roster.resolve_pending(store, q))
    p = roster.person(store, pid)
    prof = await taste.era_profile(store, q, p, limit=8)
    for d, s in prof["shelves"].items():
        print(f"== {d} window={s['window']} considered={s['considered']} outside_era={s['outside_era']} lanes={s['lanes']} err={s['errors']}")
        for it in s["items"]:
            print(f"  {it['score']:.3f} {it['name']} ({it['year']}, age {it['age_then']}) lanes={it['lanes']} because={it['because']} songs={it.get('songs', '')[:2] if it.get('songs') else ''}")
    h = await taste.taste_of_home(q, p, roster.home(store)["town"], 15000)
    print("home food", h["tag"], [(x["name"], x["distance_km"], x["dishes"][:2], x["wheelchair"]) for x in h["places"]])
    await q.aclose()
asyncio.run(main(sys.argv[1]))
