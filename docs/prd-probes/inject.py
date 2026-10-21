# harness only: simulates an inbound HMS/EMR feed by writing timeline events with the app's own add_event
import sys, datetime as dt
sys.path.insert(0,"/home/sandy/Projects/Hospital-Demo-ARD/backend")
from app.db import SessionLocal
from app.services.timeline import add_event
kind=sys.argv[1]
db=SessionLocal()
now=dt.datetime(2026,10,20,10,0,0)
if kind=="lab":
    for name,val,unit,ref,flag in (("eGFR","18","mL/min/1.73m²","> 90","low"),("Creatinine","3.4","mg/dL","0.7 - 1.3","high")):
        e=add_event(db,patient_id="pat_ravi",encounter_id="enc_ipd_1",type="lab_result",title=f"{name} — {val} {unit}",
          payload={"name":name,"value":val,"unit":unit,"reference_range":ref,"flag":flag,"review_status":"unreviewed","collected_at":now.isoformat()},
          source="hms_feed",author_type="system",author_name="Lab feed (harness)",occurred_at=now)
        print("lab",name,e.id)
if kind=="stop_metformin":
    e=add_event(db,patient_id="pat_ravi",encounter_id="enc_ipd_1",type="med_order",title="Metformin stopped",
      payload={"drug":"Metformin","kind":"inpatient","status":"stopped"},source="hms_feed",author_type="system",author_name="Order feed (harness)",occurred_at=now+dt.timedelta(minutes=5))
    print("stop",e.id)
db.commit()
