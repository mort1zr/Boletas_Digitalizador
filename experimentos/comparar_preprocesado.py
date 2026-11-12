"""Compara variantes de preprocesado (recorte y realce) con las boletas reales de referencia.

Uso: python experimentos/comparar_preprocesado.py [easyocr|tesseract]
"""
import csv, sys
from pathlib import Path
import cv2, numpy as np
RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ.parent)); sys.path.insert(0, str(RAIZ))
import ocr_service as o
import evaluar_ocr as E
MOTOR = sys.argv[1] if len(sys.argv) > 1 else "easyocr"
refs=list(csv.DictReader(open(RAIZ/"datos"/"referencia.csv",encoding="utf-8")))
def norm(x): return o._normalise_text(x)
def prep(b, crop, enh):
    im=cv2.imdecode(np.frombuffer(b,np.uint8),1)
    h,w=im.shape[:2]
    if max(h,w)>2400:
        s=2400/max(h,w); im=cv2.resize(im,(int(w*s),int(h*s)),interpolation=cv2.INTER_AREA)
    if crop:
        d=o._crop_document(im)
        if d is not None: im=d
    g=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
    a=o._estimate_skew(g)
    if abs(a)>=0.15: g=o._rotate_expand(g,a)
    if enh:
        g=cv2.bilateralFilter(cv2.createCLAHE(2.0,(8,8)).apply(g),5,35,35)
    return g
for name,(crop,enh) in {"sinrecorte_enh":(False,True),"recorte_enh":(True,True),"recorte_gris":(True,False),"sinrecorte_gris":(False,False)}.items():
    res=[]
    for r in refs:
        b=open(RAIZ/"datos"/r["archivo"],"rb").read()
        lines=E.lineas_easyocr(prep(b,crop,enh)) if MOTOR=="easyocr" else E.lineas_tesseract(prep(b,crop,enh))
        f=o.extract_fields(lines,r["regla"])
        alts=[norm(c) for c in r["comercio"].split("|")]
        res.append((r["id"],int(f.receipt_date==r["fecha"]),int(norm(f.merchant) in alts),int(f.total==r["total"])))
    print(name,"F",sum(x[1] for x in res),"C",sum(x[2] for x in res),"T",sum(x[3] for x in res),"/6",flush=True)
    print("   ",[(x[0],x[1],x[2],x[3]) for x in res],flush=True)
