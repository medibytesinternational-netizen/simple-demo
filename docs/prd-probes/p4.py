import sys; sys.path.insert(0,sys.argv[1])
from api import call
print("=== F10 on the seeded rehearsal record")
call("POST","/demo/reset?mode=rehearsal")
s,r=call("POST","/investigation-requests/generate"); print("F10 generate (rehearsal):",s,str(r)[:200])
print("=== discharge lock enforcement (rehearsal)")
s,r=call("POST","/discharge/generate"); d=r['draft']['id']; c=r['draft']['content']
print("F9 meds:",[(m['drug'],m['safety_status'],m['safety_note']) for m in c['medications']])
print("sections:",[x['heading'] for x in c['sections']])
s,a=call("POST",f"/drafts/{d}/approve",{}); print("approve F9:",s)
s,m=call("GET","/meta"); print("encounter:",m['encounter']['status'])
s,r=call("POST","/notes/generate",{"feature":"F4","transcript":"Doctor: review post discharge.\nPatient: fine."})
dd=r['draft']['id']
s,x=call("PATCH",f"/drafts/{dd}",{"content":{**r['draft']['content'],"exam":{"general":{"text":"post-discharge exam","source_event_ids":[],"source_segment_ids":[],"confidence":1,"human_authored":True},"systemic":None},"plan":{"text":"plan","source_event_ids":[],"source_segment_ids":[],"confidence":1,"human_authored":True}}})
print("patch:",s)
s,x=call("POST",f"/drafts/{dd}/approve",{}); print("approve a NEW note after the encounter is discharged/locked:",s,str(x)[:120])
s,t=call("POST","/tasks",{"title":"post-discharge task"}); print("create task after lock:",s)
