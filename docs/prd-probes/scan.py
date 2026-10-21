import re,pathlib
root=pathlib.Path("/home/sandy/Projects/Hospital-Demo-ARD")
files=[p for p in list(root.glob("backend/app/**/*.py"))+list(root.glob("frontend/src/**/*.ts*")) if p.is_file()]
pats={
 "role/RBAC/permission":r"\b(role|rbac|permission|authoriz|login|auth)\b",
 "pharmacist/pharmacy":r"pharmac",
 "nurse view":r"nurse",
 "billing role":r"billing (team|user|role)",
 "FHIR/HL7/HMS/EMR integration":r"\b(fhir|hl7|hms|emr)\b",
 "credits/metering":r"credit|meter|quota|usage_units",
 "ASR/speaker separation/diariz":r"diariz|speaker",
 "precision/false positive/metrics":r"false.positive|precision|alert_quality|feedback",
 "multi-patient param":r"patient_id\s*:\s*str",
 "websocket/streaming":r"stream|websocket|EventSource",
 "scheduler/cron/background":r"apscheduler|BackgroundTasks|asyncio\.create_task|schedule\.",
}
for name,pat in pats.items():
    hits=[]
    for p in files:
        for i,l in enumerate(p.read_text(errors='ignore').splitlines(),1):
            if re.search(pat,l,re.I): hits.append(f"{p.relative_to(root)}:{i}")
    print(f"{name}: {len(hits)} hits", hits[:6])
