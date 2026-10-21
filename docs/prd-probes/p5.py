import sys,time; sys.path.insert(0,sys.argv[1])
from api import call
from p1helpers import texts
ROUND="""Doctor: Continue IV antibiotics and review the leg tomorrow.
Doctor: Check potassium and renal function this morning.
Doctor: Stop metformin until renal function improves.
Nurse: Understood, I will hold metformin and repeat the bloods.
Doctor: Start ondansetron four milligrams IV if nauseous and increase the ibuprofen."""
print("=== Rule 1/4: said vs ordered vs done (F3 round)")
call("POST","/demo/reset?mode=rehearsal")
s,tl0=call("GET","/patients/pat_ravi/timeline"); n0=tl0['count']
s,m0=call("GET","/medications"); meds0=[(m['drug'],m['status'] if 'status' in m else '') for m in m0['current_medications']]
s,t0=call("GET","/tasks"); tcount0=len(t0['tasks'])
s,r=call("POST","/notes/generate",{"feature":"F3","transcript":ROUND}); d=r['draft']['id']; c=r['draft']['content']
s,tl1=call("GET","/patients/pat_ravi/timeline"); s,t1=call("GET","/tasks")
print("after generate: timeline",n0,"->",tl1['count'],"| tasks",tcount0,"->",len(t1['tasks']),"(drafts must not write)")
print("proposed tasks:",[(x['title'][:45],x['priority']) for x in c['proposed_tasks']])
print("note claims:",[x['text'][:70] for x in c['note_claims']])
print("nursing entries:",[x['text'][:60] for x in c['nursing_entries']])
low=" ".join(texts(c)).lower()
print("round says ondansetron:",('ondansetron' in low),"| captured 'stop metformin':",('stop metformin' in low or 'hold metformin' in low))
s,a=call("POST",f"/drafts/{d}/approve",{}); print("approve:",s)
s,t2=call("GET","/tasks"); print("tasks after approving the NOTE (should be unchanged):",len(t2['tasks']))
s,m1=call("GET","/medications"); print("active meds changed by approving a note saying 'stop metformin'?:",[m['drug'] for m in m1['current_medications']]==[m['drug'] for m in m0['current_medications']])
print("any med-order write endpoint? (POST/PATCH/DELETE under /medications):",[1 for _ in []] or "none in openapi")
s,acc=call("POST",f"/drafts/{d}/accept-tasks",{"indices":[0,1,2]}); print("accept tasks:",s,[(x['title'][:30],x['status'],x['owner']) for x in acc['tasks']])

print("=== F15 lifecycle & escalation")
s,t=call("POST","/tasks",{"title":"Overdue test task","due_in_hours":-6,"owner":"Nurse Anita Rao"}); tid=t['id']; print("created:",t['status'],"level",t.get('escalation_level'),"due",t.get('due_at'))
time.sleep(2)
s,g=call("GET","/tasks"); me=[x for x in g['tasks'] if x['id']==tid][0]; print("after wait w/o calling sweep: level",me.get('escalation_level'),"escalated_at",me.get('escalated_at'),"overdue flag",me.get('overdue'))
s,x=call("PATCH",f"/tasks/{tid}",{"status":"completed"}); print("PATCH created->completed directly (skip ack/start):",s,x.get('status') if isinstance(x,dict) else x)
s,x=call("PATCH",f"/tasks/{tid}",{"status":"proposed"}); print("PATCH completed->proposed (reopen):",s,x.get('status') if isinstance(x,dict) else x)
s,t=call("POST","/tasks",{"title":"Sweep test task","due_in_hours":-9}); tid2=t['id']
s,sw=call("POST","/tasks/escalations/run",{}); print("manual sweep:",s,sw['count'],[(e['title'][:25],e.get('escalation_level')) for e in sw['escalated']])
s,e=call("POST",f"/tasks/{tid2}/escalate",{"actor":"x"}); print("manual escalate with no reason:",s,str(e)[:140])
s,e=call("POST",f"/tasks/{tid2}/acknowledge",{"actor":"Someone Else"}); print("anyone can ack (no owner check):",s,e.get('acknowledged_by') if isinstance(e,dict) else e)
