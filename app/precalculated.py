"""Validate the supplied initial stock plans independently of cached formulas."""
import math
from .imports import read_sheet,parse_plate_rows,header_key,numeric

PMOL=.05
BASIS='Imported resuspension plan (unmeasured)'


def precalculated_rows(content,filename):
    raw=read_sheet(content,filename)
    if len(raw)>5000:raise ValueError('A plate import can contain at most 5,000 rows.')
    prepared=[];audit=[]
    for number,row in enumerate(raw,2):
        clean={header_key(k):v for k,v in row.items()}
        def value(*keys):return next((clean[k] for k in keys if k in clean and clean[k] not in (None,'')),None)
        stock=numeric(value('concngul','stockngul','concentrationngul'),'Stock concentration')
        mass=numeric(value('yieldng','massng'),'Yield')
        water=numeric(value('h2o','resuspensionul'),'Resuspension volume')
        supplied_mass=numeric(value('mass005pmol'),'Mass (0.05 pmol)')
        supplied_use=numeric(value('volume11','volume'),'Reaction volume')
        if any(v is None for v in (stock,mass,water,supplied_mass,supplied_use)):
            raise ValueError(f'Row {number}: initial plate maps require numeric Conc (ng/uL), Yield (ng), H2O, Mass (0.05pmol) and Volume values; recalculate and save missing formula results.')
        item=dict(row);item['Stock ng/uL']=stock;item['Resuspension uL']=mass/stock
        parsed=parse_plate_rows([item])[0]
        physical=len(parsed['construct_sequence'] or parsed['sequence'])
        expected_mass=physical*660*PMOL/1000;expected_use=expected_mass/stock
        corrections=[]
        for label,supplied,expected in [('H2O',water,mass/stock),('Mass (0.05pmol)',supplied_mass,expected_mass),('Volume',supplied_use,expected_use)]:
            if not math.isclose(supplied,expected,rel_tol=1e-8,abs_tol=1e-6):
                corrections.append({'field':label,'supplied':supplied,'calculated':expected})
        parsed['concentration_basis']=BASIS
        parsed.update(default_stock_ng_ul=stock,default_resuspension_ul=mass/stock,default_concentration_basis=BASIS)
        warnings=[]
        if mass/stock>=100:warnings.append('Resuspension ≥100 µL')
        if not 1<=expected_use<=5:warnings.append('Aliquot outside 1–5 µL')
        audit.append({'filename':filename,'plate_id':parsed['plate_id'],'well':parsed['well'],'name':parsed['name'],
                      'physical_length':physical,'yield_ng':mass,'stock_ng_ul':stock,'resuspension_ul':mass/stock,
                      'target_ng':expected_mass,'use_ul':expected_use,'supplied_resuspension_ul':water,
                      'supplied_target_ng':supplied_mass,'supplied_use_ul':supplied_use,'corrections':corrections,'warnings':warnings})
        prepared.append(parsed)
    # Validate duplicates across all blocks, not just within individual records.
    keys=[(r['plate_id'],r['well']) for r in prepared]
    if len(set(keys))!=len(keys):raise ValueError('Duplicate plate/well in this file.')
    if not prepared:raise ValueError('No fragments found.')
    return prepared,audit
