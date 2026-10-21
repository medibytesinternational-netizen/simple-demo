import sys; sys.path.insert(0,sys.argv[1])
from api import call
call("POST","/demo/reset?mode=start")
s,r=call("POST","/discharge/generate"); d=r['draft']['id']
s,a=call("POST",f"/drafts/{d}/approve",{}); print("approve EMPTY F9 on empty record:",s,str(a)[:200])
s,m=call("GET","/meta"); print("encounter status now:",m['encounter']['status'])
s,r=call("POST","/notes/generate",{"feature":"F2","transcript":"Doctor: admit for observation.\nPatient: ok thanks."}); 
print("after discharge, can a new note be generated/approved? generate:",s)
