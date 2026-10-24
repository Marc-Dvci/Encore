"""Resolve every favourite in the demo home and print what matched."""
import asyncio
import sys
sys.path.insert(0, ".")
from encore.config import load_config
from encore.store import Store
from encore.qloo import Qloo
from encore import roster

async def main():
    cfg = load_config()
    store = Store(cfg.db_path)
    q = Qloo(cfg, store)
    roster.load_home(store, cfg.home_file, reset=True)
    roster.register_privacy(store, q.guard)
    for f in store.q("SELECT f.*, p.birth_year FROM favourites f JOIN people p ON p.id=f.person_id"):
        r = await roster.resolve_favourite(q, f["label"], f["kind"], f["birth_year"])
        top = [(c["name"], c["year"], round(c["popularity"], 3)) for c in r["candidates"][:3]]
        print(f"{f['person_id']:<11} {f['kind']:<8} {f['label']:<28} -> {r['status']:<11} {r.get('entity_name')}  {top}")
    await q.aclose()
asyncio.run(main())
