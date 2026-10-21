import json, urllib.request, urllib.error, uuid
BASE="http://127.0.0.1:8000/api"
def call(method, path, body=None, raw=False):
    data=None if body is None else json.dumps(body).encode()
    r=urllib.request.Request(BASE+path, data=data, method=method, headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            t=resp.read()
            return resp.status, (t.decode() if raw else json.loads(t))
    except urllib.error.HTTPError as e:
        t=e.read().decode()
        try: return e.code, json.loads(t)
        except Exception: return e.code, t
def upload(path, filename, content, ctype):
    b=uuid.uuid4().hex
    body=(f"--{b}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\nContent-Type: {ctype}\r\n\r\n").encode()+content+f"\r\n--{b}--\r\n".encode()
    r=urllib.request.Request(BASE+path,data=body,method="POST",headers={"Content-Type":f"multipart/form-data; boundary={b}"})
    try:
        with urllib.request.urlopen(r,timeout=60) as resp: return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as e:
        t=e.read().decode()
        try: return e.code, json.loads(t)
        except Exception: return e.code, t
