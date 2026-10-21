import sys; sys.path.insert(0,sys.argv[1])
from api import call
from p1helpers import texts
ASTHMA="Doctor: What brings you in?\nPatient: Dry cough and wheeze at night for two weeks.\nDoctor: Peak flow is 62 percent. This looks like mild asthma. Start salbutamol as needed."
def show(label,r,words=("cellulitis","leg","metformin","ckd","egfr","flucloxacillin","warfarin","ibuprofen","58")):
    c=r['draft']['content'] if 'draft' in r else r
    t=" | ".join(texts(c)); low=t.lower()
    hit=[w for w in words if w in low]
    print(f"[{label}] ravi-terms present: {hit}")
    print("   ",t[:260])
print("=== P3 fresh start, empty timeline: do drafts invent Ravi content?")
print(call("POST","/demo/reset?mode=start"))
s,tl=call("GET","/patients/pat_ravi/timeline"); print("timeline events:",tl['count'],[e['type'] for e in tl['events']])
s,st=call("GET","/patients/pat_ravi/state"); print("active meds",st['active_meds'],"labs",st['latest_labs'])
for f in ("F2","F4"):
    s,r=call("POST","/notes/generate",{"feature":f,"transcript":ASTHMA}); print(f,s); show(f,r)
s,r=call("POST","/discharge/generate"); print("F9",s); show("F9",r); print("   sections:",[x['heading'] for x in r['draft']['content']['sections']], "meds:",r['draft']['content']['medications'])
s,r=call("POST","/icu/flow-sheet/generate"); print("F7",s, str(r)[:150])
s,r=call("POST","/investigation-requests/generate"); print("F10",s); show("F10",r)
s,r=call("POST","/referrals/generate",{}); print("F11",s); show("F11",r)
s,r=call("POST","/medications/reconciliation/generate"); print("F6",s,str(r)[:200])
s,r=call("GET","/revenue/claim-prep"); print("F12",s,str(r)[:300])
s,r=call("GET","/revenue/leakage"); print("F13",s,str(r)[:200])
s,r=call("GET","/discharge/readiness"); print("readiness",r)
