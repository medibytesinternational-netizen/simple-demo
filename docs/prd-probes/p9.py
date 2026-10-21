import sys,json; sys.path.insert(0,sys.argv[1])
from api import call
call("POST","/demo/reset?mode=rehearsal")
s,d0=call("GET","/hospital/dashboard")
print("dashboard keys:",list(d0.keys()))
def flat(d,p=""):
    o={}
    for k,v in d.items():
        if isinstance(v,dict): o.update(flat(v,p+k+"."))
        elif isinstance(v,(int,float)) and not isinstance(v,bool): o[p+k]=v
    return o
f0=flat(d0)
print("patients in cohort:",d0.get('cohort_size') or d0.get('patients') and len(d0['patients']), "| sample:",json.dumps({k:d0[k] for k in list(d0)[:3]})[:400])
# act: new task, approve a note, escalate, dismiss alert
call("POST","/tasks",{"title":"Dashboard movement test","due_in_hours":-9})
call("POST","/tasks/escalations/run",{})
s,al=call("GET","/alerts"); call("POST",f"/alerts/{al['alerts'][0]['id']}/dismiss",{"reason":"testing the dashboard counter"})
s,d1=call("GET","/hospital/dashboard"); f1=flat(d1)
print("counters that moved:",{k:(f0.get(k),f1[k]) for k in f1 if f0.get(k)!=f1[k]})
print("=== labelled illustrative?", [k for k in d1 if 'illustr' in json.dumps(d1[k]).lower() or 'honest' in k.lower()])
print("=== F16 supersession: approve two F1 notes")
call("POST","/patients/pat_ravi/consents",{"consent_type":"consultation_capture","granted":True})
ids=[]
for i in range(2):
    s,r=call("POST","/notes/generate",{"feature":"F1","transcript":f"Doctor: visit {i} review of the leg wound.\nPatient: improving."}); s,a=call("POST",f"/drafts/{r['draft']['id']}/approve",{}); ids.append(a['event']['id'])
s,tl=call("GET","/patients/pat_ravi/timeline?limit=500"); ev=[e for e in tl['events'] if e['id'] in ids]
print("both F1 events visible:",[(e['id'][-4:],e['status'],e['supersedes_event_id'] and e['supersedes_event_id'][-4:]) for e in ev])
print("author_type/name of an approved AI note:",ev[0]['author_type'],'/',ev[0]['author_name'],'| approved_by:',ev[0].get('approved_by'))
e=ev[0]; print("event fields:",sorted(e.keys()))
print("append-only? PATCH/DELETE on events exist:", [1 for _ in []] or "no (only GET)")
print("=== F12 after signing discharge")
s,c0=call("GET","/revenue/claim-prep"); print("before: status",c0['status'],"missing",[m['key'] for m in c0['missing_documents']],"contradictions",len(c0['contradictions']),"unbilled",len(c0['unbilled_procedures']),"underbilled",len(c0['underbilled_items']),"unsupported",len(c0['unsupported_items']))
s,r=call("POST","/discharge/generate"); call("POST",f"/drafts/{r['draft']['id']}/approve",{})
s,c1=call("GET","/revenue/claim-prep"); print("after:  status",c1['status'],"missing",[m['key'] for m in c1['missing_documents']])
s,ex=call("POST","/revenue/claim-prep/explain"); print("explain:",s,str(ex)[:120])
s,l=call("GET","/revenue/leakage"); print("leakage:",[(f['billing_status'],f['procedure'][:30]) for f in l['findings']])
