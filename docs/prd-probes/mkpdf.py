import sys
lines=["CITY LAB REPORT","Patient: Asha Verma  MRN ZZ-999","Creatinine 1.0 mg/dL (0.7-1.3)","eGFR 88 mL/min/1.73m2 (> 90)","Potassium 4.1 mmol/L (3.5-5.1)"]
stream="BT /F1 12 Tf 50 750 Td 16 TL "+" ".join(f"({l}) Tj T*" for l in lines)+" ET"
objs=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
 b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
 f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream".encode(),b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
out=b"%PDF-1.4\n"; offs=[]
for i,o in enumerate(objs,1):
    offs.append(len(out)); out+=f"{i} 0 obj\n".encode()+o+b"\nendobj\n"
x=len(out); out+=f"xref\n0 {len(objs)+1}\n0000000000 65535 f \n".encode()+b"".join(f"{o:010d} 00000 n \n".encode() for o in offs)
out+=f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{x}\n%%EOF".encode()
open(sys.argv[1],"wb").write(out)
