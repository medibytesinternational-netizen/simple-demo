import sys; sys.path.insert(0,sys.argv[1])
from api import call
from p1helpers import texts
T="Doctor: progress review.\nPatient: feeling better today."
call("POST","/demo/reset?mode=rehearsal")
print("=== F2 allergy gate")
s,r=call("POST","/notes/generate",{"feature":"F2","transcript":T}); d=r['draft']['id']
print("allergies_to_verify:",r['draft']['content']['allergies_to_verify'])
print("proposed_orders:",[o['order'][:50] for o in r['draft']['content']['proposed_orders']])
s,x=call("POST",f"/drafts/{d}/approve",{}); print("approve before verify:",s,str(x)[:90])
call("POST",f"/drafts/{d}/verify-allergy",{"substance":"Penicillin — rash"}); s,x=call("POST",f"/drafts/{d}/approve",{}); print("approve after human verify:",s)
s,m=call("GET","/medications"); print("proposed orders became active orders? (should be no):",[x['drug'] for x in m['current_medications']])
print("=== F4 gate")
s,r=call("POST","/notes/generate",{"feature":"F4","transcript":T}); d=r['draft']['id']
print("F4 exam/plan:",r['draft']['content']['exam'],r['draft']['content']['plan'])
s,x=call("POST",f"/drafts/{d}/approve",{}); print("approve with empty exam/plan:",s)
print("F4 'what changed since last note' — objective:",r['draft']['content']['objective']['text'])
print("=== F7 flow sheet")
s,r=call("POST","/icu/flow-sheet/generate"); c=r['draft']['content']; e=c['entries']
print("entries:",len(e),"| with unit:",sum(1 for x in e if x['unit']),"| with timestamp:",sum(1 for x in e if x['recorded_at']),"| with device:",sum(1 for x in e if x['device']),"| with source id:",sum(1 for x in e if x['source_event_id']))
print("sample:",e[:2]); print("not_documented:",c['not_documented'])
print("=== F11 lifecycle")
s,r=call("POST","/referrals/generate",{"specialty":"Cardiology"}); c=r['draft']['content']
print("asked for Cardiology ->",c['specialty'],"| question:",c['question']['text'][:80])
d=r['draft']['id']; s,x=call("POST",f"/drafts/{d}/approve",{}); rid=x['event']['payload']['referral_id']; s,g=call("GET","/referrals"); print("on approve status:",[q['status'] for q in g['referrals'] if q['id']==rid])
print("ack:",call("POST",f"/referrals/{rid}/acknowledge",{})[0],"complete:",call("POST",f"/referrals/{rid}/complete",{"response_summary":"Advise renal dosing"})[0])
s,tl=call("GET","/patients/pat_ravi/timeline"); print("timeline has consult response:",any(e['type']=='referral_consult' for e in tl['events']))
