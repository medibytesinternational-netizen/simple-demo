def texts(o,out=None):
    out=[] if out is None else out
    if isinstance(o,dict):
        if isinstance(o.get('text'),str): out.append(o['text'])
        for k,v in o.items():
            if k!='text': texts(v,out)
    elif isinstance(o,list):
        for v in o: texts(v,out)
    elif isinstance(o,str) and len(o)>3: out.append(o)
    return out
