import sys,json,time; sys.path.insert(0,sys.argv[1])
import api; api.BASE="http://127.0.0.1:8001/api"
from api import call
from p1helpers import texts
ASTHMA = """Doctor: Good morning, what brings you in today?
Patient: I have had a dry cough and wheeze at night for two weeks, worse after cycling.
Doctor: Any fever or chest pain?
Patient: No fever. No chest pain. I use no regular medicines.
Doctor: Your chest has scattered expiratory wheeze and peak flow is 62 percent of predicted.
Doctor: This looks like mild persistent asthma. I will start salbutamol inhaler two puffs as needed and beclometasone 100 micrograms twice daily.
Doctor: Review in four weeks with a peak flow diary."""
call("POST","/demo/reset?mode=rehearsal")
t=time.time(); s,r=call("POST","/notes/generate",{"feature":"F1","transcript":ASTHMA}); print("status",s,round(time.time()-t,1),"s")
if s==200:
    print("llm:",r['llm']); c=r['draft']['content']; low=" ".join(texts(c)).lower()
    for x in texts(c)[:12]: print("  -",x[:130])
    print("reflects asthma input:",any(w in low for w in ("asthma","wheeze","salbutamol")),"| still canned cellulitis:", "cellulitis" in low)
    s2,llm=call("GET","/audit?limit=5"); 
else: print(str(r)[:300])
