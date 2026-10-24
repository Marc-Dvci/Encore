import asyncio
import sys
import json
import time
sys.path.insert(0,'.')
from encore.config import load_config
from encore.store import Store
from encore.qloo import Qloo
from encore import roster, group, common
cfg=load_config()
st=Store(cfg.db_path)
q=Qloo(cfg,st)
async def main():
    t0=time.time()
    roster.register_privacy(st,q.guard)
    res=roster.people(st,'resident')
    g=await group.film_pick(st,q,res)
    p=g['pick']
    print('PICK',p['name'],p['year'],p['duration'],'min_pct',p['min_pct'],'least',p['least_served'],'mean',p['mean_pct'])
    for a in g['alternatives']:
        print(' ALT',a)
    print(' pool',len(g['candidates']),'excluded',g['excluded'][:6])
    for c in g['candidates'][:8]:
        print('  ',c['name'],c['year'],c['min_pct'],c['least_served'],c['mean_pct'],c['nominated_by'])
    m=await group.music_hour(st,q,res)
    print('MUSIC',[ (x['name'],x['song']) for x in m['playlist']])
    print(' cov',m['coverage'])
    cg=await common.common_ground(q,roster.person(st,'r-tomasz'),roster.person(st,'c-priya'))
    print('COMMON',json.dumps(cg,ensure_ascii=False)[:900])
    print('live',q.live_calls, round(time.time()-t0,1),'s')
    await q.aclose()
asyncio.run(main())
