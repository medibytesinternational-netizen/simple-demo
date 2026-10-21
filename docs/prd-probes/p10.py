import sys; sys.path.insert(0,sys.argv[1])
from api import call
s,d=call("GET","/hospital/dashboard"); pts=d['patients']; print("cohort sample:",pts[1] if len(pts)>1 else pts)
for p in pts[:5]:
    pid=p.get('patient_id') or p.get('id'); s,x=call("GET",f"/patients/{pid}/state"); print(pid,s,(x.get('patient',{}).get('name') if isinstance(x,dict) else str(x)[:60]), "meds",len(x.get('active_meds',[])) if isinstance(x,dict) else '-')
s,t=call("GET","/patients/pat_other/timeline"); print("non-existent patient:",s)
