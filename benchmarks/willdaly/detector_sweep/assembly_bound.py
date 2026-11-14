#!/usr/bin/env python3
"""Upper bound on R-group assembly with H caps and two-ended linkers, per detector setting.

Run read_extra.py first. Tries answer-key-guided joins of same-page fragments, so
each count is the most a perfect pairing step could gain, not a pipeline result.
Extends reports/1.4-group-report/assembly_example.py, which only joins pairs.
"""
import ast
import csv
import importlib.util
import itertools
from collections import Counter
from pathlib import Path

import pandas as pd
from rdkit import Chem, RDLogger

RDLogger.DisableLog('rdApp.*')
REPO = Path(__file__).resolve().parents[3]
S = REPO / 'benchmarks/results/willdaly/2026-11-06_detector-sweep_internal'
spec=importlib.util.spec_from_file_location('ax',REPO/'reports/1.4-group-report/assembly_example.py');ax=importlib.util.module_from_spec(spec);spec.loader.exec_module(ax)
x=pd.read_csv(S/'extra_read.csv');x['paper']=x.paper.astype(str);x['configs']=x.configs.map(ast.literal_eval)
gt={}
for row in csv.DictReader(open(ax.GT,encoding='utf-8-sig')): gt.setdefault(str(row['paperID']),set()).add(ax.canon(row['canonical_SMILES']))
base=pd.read_csv(ax.RUN);base['paper_id']=base.paper_id.astype(str)
def stars(m): return [a.GetIdx() for a in m.GetAtoms() if a.GetAtomicNum()==0]
def link(a,ai,b,bi):
    """Bond star ai of a to star bi of b; other stars stay."""
    a,b=Chem.RWMol(a),Chem.RWMol(b)
    a.GetAtomWithIdx(ai).SetAtomMapNum(1);b.GetAtomWithIdx(bi).SetAtomMapNum(1)
    try:
        m=Chem.molzip(a,b);Chem.SanitizeMol(m);return m
    except Exception: return None
def cap(m,idxs):
    r=Chem.RWMol(m)
    for i in idxs: r.GetAtomWithIdx(i).SetAtomicNum(1)
    try:
        o=Chem.RemoveHs(r);Chem.SanitizeMol(o);return o
    except Exception: return None
def key(m): return Chem.MolToSmiles(m) if m is not None else None
def run(ex):
    rows=[(a.paper_id,a.page,a.smiles) for a in base.itertuples() if isinstance(a.smiles,str)]+ex
    pg={}
    for p,g,s in rows:
        m=Chem.MolFromSmiles(s)
        if m is None or '*' not in s: continue
        st=stars(m)
        if 1<=len(st)<=3 and m.GetNumHeavyAtoms()-len(st)>=1: pg.setdefault((p,g),[]).append(m)
    hit=set();tried=0
    for (p,g),ms in pg.items():
        T=gt[p]
        # H caps on any subset of stars, then joins through what remains
        for m in ms:
            st=stars(m)
            for r in range(1,len(st)+1):
                for sub in itertools.combinations(st,r):
                    if len(sub)==len(st):
                        tried+=1;k=key(cap(m,sub))
                        if k in T: hit.add((p,k,'cap'))
        ones=[m for m in ms if len(stars(m))==1]
        twos=[m for m in ms if len(stars(m))==2]
        for a,b in itertools.combinations(ones,2):
            tried+=1;k=key(link(a,stars(a)[0],b,stars(b)[0]))
            if k in T: hit.add((p,k,'pair'))
        for l in twos:
            s0,s1=stars(l)
            for a,b in itertools.permutations(ones,2):
                m=link(l,s0,a,stars(a)[0])
                if m is None: continue
                st=stars(m)
                if len(st)!=1: continue
                tried+=1;k=key(link(m,st[0],b,stars(b)[0]))
                if k in T: hit.add((p,k,'linker'))
            for a in ones:                       # scaffold with two stars: one piece plus one H
                for si,so in ((s0,s1),(s1,s0)):
                    m=link(l,si,a,stars(a)[0])
                    if m is None: continue
                    st=stars(m)
                    if len(st)==1:
                        tried+=1;k=key(cap(m,st))
                        if k in T: hit.add((p,k,'capjoin'))
    return tried,hit
direct={(a.paper_id,ax.canon(a.smiles)) for a in base.itertuples() if isinstance(a.smiles,str)}
direct={(p,c) for p,c in direct if c in gt[p]}
def new(h): return {(p,k) for p,k,_ in h}-direct
t0,h0=run([]);b=new(h0);print('baseline tried',t0,'assembled new',len(b),Counter(p for p,_ in b),Counter(w for _,_,w in h0))
rows=[]
for cfg,th in [('page960',.26),('page1280',.5),('page1280',.26),('page1600',.5),('page1920',.5),('page1920',.1),('tile1600',.5),('tile1600',.1)]:
    ex=[(t.paper,t.page,t.smiles) for t in x.itertuples() if (cfg,th) in t.configs and isinstance(t.smiles,str)]
    t,h=run(ex);n=new(h);rows.append((cfg,th,len(ex),t,len(n),len(n-b),dict(Counter(p for p,_ in n-b))))
t=pd.DataFrame(rows,columns=['config','conf','extra','tried','assembled_new','gain','gain_by_paper']);t.to_csv(S/'assembly_bound.csv',index=False);print(t.to_string(index=False))
