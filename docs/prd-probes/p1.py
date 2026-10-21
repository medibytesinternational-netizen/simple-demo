import sys; sys.path.insert(0,sys.argv[1])
from api import call
import json
def texts(o,out=None):
    out=[] if out is None else out
    if isinstance(o,dict):
        if isinstance(o.get('text'),str): out.append(o['text'])
        for k,v in o.items():
            if k!='text': texts(v,out)
    elif isinstance(o,list):
        for v in o: texts(v,out)
    return out

ASTHMA = """Doctor: Good morning, what brings you in today?
Patient: I have had a dry cough and wheeze at night for two weeks, worse after cycling.
Doctor: Any fever or chest pain?
Patient: No fever. No chest pain. I use no regular medicines.
Doctor: Your chest has scattered expiratory wheeze and peak flow is 62 percent of predicted.
Doctor: This looks like mild persistent asthma. I will start salbutamol inhaler two puffs as needed and beclometasone 100 micrograms twice daily.
Doctor: Review in four weeks with a peak flow diary."""

print("=== P1 F1 with non-seed asthma transcript (rehearsal data)")
call("POST","/demo/reset?mode=rehearsal")
s,r=call("POST","/notes/generate",{"feature":"F1","transcript":ASTHMA})
print(s, r['llm'])
for t in texts(r['draft']['content']): print("  -",t[:140])
joined=" ".join(texts(r['draft']['content'])).lower()
print("mentions asthma/wheeze/salbutamol:", any(w in joined for w in ("asthma","wheeze","salbutamol","cough")))
print("mentions cellulitis/leg/metformin:", [w for w in ("cellulitis","leg","metformin") if w in joined])

print("=== P18 evidence resolution on that draft")
c=r['draft']['content']; ids=set(r['draft']['evidence_event_ids'])
print("evidence ids:",ids)
for i in list(ids)[:5]:
    s2,e=call("GET",f"/events/{i}"); print("  ",i,s2, e.get('type') if isinstance(e,dict) else e)
def claims(o,out):
    if isinstance(o,dict):
        if 'text' in o and 'source_event_ids' in o: out.append(o)
        for v in o.values(): claims(v,out)
    elif isinstance(o,list):
        for v in o: claims(v,out)
cl=[]; claims(c,cl)
print("claims:",len(cl),"with no source:",sum(1 for x in cl if not x['source_event_ids'] and not x.get('source_segment_ids')))
segs=len(ASTHMA.splitlines()); print("transcript segs:",segs,"cited segs:",sorted({s_ for x in cl for s_ in x.get('source_segment_ids',[])}))

print("=== P2 consent gate on fresh start")
call("POST","/demo/reset?mode=start")
s,r=call("POST","/notes/generate",{"feature":"F1","transcript":ASTHMA})
d=r['draft']['id']
print("generate w/o consent:",s)
s,x=call("POST",f"/drafts/{d}/approve",{}); print("approve w/o consent:",s,str(x)[:160])
import urllib.request
s,x=call("POST","/notes/transcribe"); print("transcribe w/o file/consent:",s,str(x)[:120])
