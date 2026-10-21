import sys; sys.path.insert(0,sys.argv[1])
from api import call, upload
from p1helpers import texts
sp=sys.argv[1]
print("=== F8: upload a DIFFERENT text-layer PDF (creatinine 1.0, eGFR 88, K 4.1)")
call("POST","/demo/reset?mode=rehearsal")
s,doc=upload("/documents/upload","foreign_lab.pdf",open(sp+"/foreign_lab.pdf","rb").read(),"application/pdf")
print(s,doc.get('ocr_status'),[(f['name'],f['value'],f['confidence']) for f in doc['extracted']['fields']] if isinstance(doc,dict) else doc)
print("  -> values from the uploaded file?", any(f['value']=='1.0' for f in doc['extracted']['fields']))
did=doc['id']
print("=== F8 commit gate")
s,x=call("POST",f"/documents/{did}/commit"); print("commit before confirming low-confidence field:",s,str(x)[:160])
fields=doc['extracted']['fields']
for i,f in enumerate(fields):
    if f['confidence']<0.8:
        s,x=call("POST",f"/documents/{did}/confirm-field",{"index":i}); print("confirm",f['name'],s)
print("=== F5/F6/F9/F11/F16 reuse: confirm eGFR->18 via human edit, commit")
for i,f in enumerate(fields):
    if f['name']=='eGFR': call("POST",f"/documents/{did}/confirm-field",{"index":i,"value":"18"})
s,a0=call("GET","/alerts"); r1_before=[x for x in a0['alerts'] if x['rule_id']=='R1']
s,x=call("POST",f"/documents/{did}/commit"); print("commit:",s,"new alerts:",x.get('new_alerts') if isinstance(x,dict) else x)
s,a1=call("GET","/alerts"); r1=[(x['id'],x['status'],x['explanation'][:70]) for x in a1['alerts'] if x['rule_id']=='R1']
print("R1 alerts now:",len(r1),r1)
s,tl=call("GET","/patients/pat_ravi/timeline"); labs=[(e['title'],e['source'],e['author_name']) for e in tl['events'] if e['type']=='lab_result']
print("timeline lab events from F8:",[l for l in labs if l[1]=='F8'])
s,st=call("GET","/patients/pat_ravi/state"); print("state latest eGFR:",[l['value'] for l in st['latest_labs'] if l['name']=='eGFR'])
s,r=call("POST","/referrals/generate",{}); print("F11 sees new eGFR:", '18' in str(r['draft']['content']['question']['text']), '|',r['draft']['content']['question']['text'][:110])
print("   F11 history text still hard-coded '58-year-old man': ", '58-year-old' in r['draft']['content']['history']['text'], "eGFR 22 mentioned:", '22' in r['draft']['content']['history']['text'])
s,r=call("POST","/notes/generate",{"feature":"F4","transcript":"Doctor: progress review.\nPatient: feeling better today."}); print("F4 uses any lab? ", any(w in " ".join(texts(r['draft']['content'])).lower() for w in ("egfr","creatinine","18")))
s,r=call("POST","/discharge/generate"); inv=[p['text'] for sct in r['draft']['content']['sections'] if sct['heading']=='Investigations' for p in sct['paragraphs']]; print("F9 investigations:",inv)
s,r=call("POST","/medications/reconciliation/generate"); md=[d for d in r['reconciliation']['discrepancies'] if d['kind']=='contraindicated']; print("F6 metformin explanation:",[ (d['explanation'][:70],d['home_value']) for d in md])
