import sys,json; sys.path.insert(0,sys.argv[1])
import api; api.BASE="http://127.0.0.1:8001/api"
from api import call
s,d=call("GET","/drafts?feature=F1&limit=1"); dr=d['drafts'][0]
print(json.dumps(dr['content'],indent=1)[:1500])
print("status",dr['status'],"evidence",dr['evidence_event_ids'])
