"""Persistent planning rules and linked inventory quantities."""
import json
import math

from pydantic import BaseModel, Field, model_validator

from . import database as store
from .exports import resuspension_plan


class InventoryRules(BaseModel):
    backbone_pmol:float=Field(.05,gt=0,allow_inf_nan=False)
    insert_ratio:float=Field(1,gt=0,allow_inf_nan=False)
    preferred_resuspension_ul:float=Field(50,gt=0,allow_inf_nan=False)
    max_resuspension_ul:float=Field(99.99,gt=0,allow_inf_nan=False)
    min_input_volume_ul:float=Field(1,gt=0,allow_inf_nan=False)
    max_input_volume_ul:float=Field(5,gt=0,allow_inf_nan=False)

    @model_validator(mode='after')
    def ordered_limits(self):
        if self.min_input_volume_ul>self.max_input_volume_ul:
            raise ValueError('Minimum aliquot cannot exceed maximum aliquot.')
        return self


def get_rules():
    with store.connection() as db:
        row=db.execute("SELECT value FROM settings WHERE key='inventory_rules'").fetchone()
    return InventoryRules.model_validate(json.loads(row['value']) if row else {}).model_dump()


def save_rules(rules):
    values=InventoryRules.model_validate(rules).model_dump()
    with store.connection() as db:
        db.execute("INSERT INTO settings(key,value) VALUES('inventory_rules',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps(values),))
    return values


def inventory_records(parts=None):
    parts=store.fragments() if parts is None else parts
    rules=get_rules()
    plans=resuspension_plan(parts,rules | {'resuspension_mode':'constrained','no_backbone':True})
    records=[]
    for part,plan in zip(parts,plans):
        row_rules=InventoryRules.model_validate(part.get('stock_rules') or rules).model_dump()
        if part.get('stock_rules'):
            plan=resuspension_plan([part],row_rules | {'resuspension_mode':'constrained','no_backbone':True})[0]
        saved=bool(part.get('stock_saved'))
        stock=part.get('stock_ng_ul') if saved else plan['target_ng_ul']
        volume=part.get('resuspension_ul') if saved else plan['resuspension_ul']
        mass=part.get('yield_ng')
        if saved and volume is None and mass is not None and stock:
            volume=mass/stock
        if saved and stock is None and mass is not None and volume:
            stock=mass/volume
        target=plan['target_ng']
        aliquot=target/stock if target is not None and stock else None
        warnings=[] if saved else list(plan['warnings'])
        if saved and aliquot is not None and not row_rules['min_input_volume_ul']-1e-9<=aliquot<=row_rules['max_input_volume_ul']+1e-9:
            warnings.append('Saved stock requires an aliquot outside the current rules.')
        if saved and volume is not None and volume>row_rules['max_resuspension_ul']:
            warnings.append('Saved resuspension exceeds the current cap.')
        if saved and mass is not None and target is not None and mass<target:
            warnings.append('Insufficient yield for one reaction.')
        records.append({'id':part['id'],'yield_ng':mass,'default_yield_ng':part.get('default_yield_ng'),
            'yield_locked':bool(part.get('yield_locked',True)),
            'stock_ng_ul':stock,'resuspension_ul':volume,'saved':saved,'warnings':warnings,
            'input_volume_ul':aliquot,'target_ng':target,'default_stock_ng_ul':part.get('default_stock_ng_ul') if part.get('default_stock_ng_ul') is not None else plan['target_ng_ul'],
            'default_resuspension_ul':part.get('default_resuspension_ul') if part.get('default_resuspension_ul') is not None else plan['resuspension_ul'],'applied_rules':part.get('stock_rules'),'rules':row_rules,'concentration_basis':part.get('concentration_basis')})
    return records


def linked_update(part,updates,derive=None):
    numeric={'yield_ng','stock_ng_ul','resuspension_ul'}
    changed=numeric.intersection(updates)
    if not changed:
        return updates
    record=inventory_records([part])[0]
    values={key:record[key] for key in numeric}
    values.update({key:updates[key] for key in changed})
    if derive is None:
        derive='yield_ng' if {'stock_ng_ul','resuspension_ul'}<=changed and updates.get('stock_ng_ul') and updates.get('resuspension_ul') else 'resuspension_ul' if 'stock_ng_ul' in changed else 'stock_ng_ul'
    if derive=='yield_ng':
        values['yield_ng']=values['stock_ng_ul']*values['resuspension_ul'] if values['stock_ng_ul'] and values['resuspension_ul'] else None
    elif derive=='resuspension_ul':
        values['resuspension_ul']=values['yield_ng']/values['stock_ng_ul'] if values['yield_ng'] is not None and values['stock_ng_ul'] else None
    elif derive=='stock_ng_ul':
        if values['resuspension_ul'] is None and values['yield_ng'] is not None:
            planned=resuspension_plan([part | {'yield_ng':values['yield_ng']}],(part.get('stock_rules') or get_rules()) | {'resuspension_mode':'constrained','no_backbone':True})[0]
            values['resuspension_ul']=planned['resuspension_ul']
        values['stock_ng_ul']=values['yield_ng']/values['resuspension_ul'] if values['yield_ng'] is not None and values['resuspension_ul'] else None
    if any(value is not None and (not math.isfinite(value) or value<=0) for value in values.values()):
        raise ValueError('Yield, stock and resuspension must be positive and finite.')
    return updates | values | {'stock_saved':1,'concentration_basis':'recorded linked values' if values['stock_ng_ul'] else 'unknown'}


def reset_records(ids=None):
    with store.connection() as db:
        if ids is not None:
            found={row['id'] for row in db.execute('SELECT id FROM fragments WHERE '+store.ACTIVE_FRAGMENTS)}
            if set(ids)-found:
                raise ValueError('Fragment not found.')
        clause=' WHERE '+store.ACTIVE_FRAGMENTS+('' if ids is None else ' AND id IN ('+','.join('?' for _ in ids)+')')
        cursor=db.execute("UPDATE fragments SET yield_ng=default_yield_ng,stock_ng_ul=default_stock_ng_ul,resuspension_ul=default_resuspension_ul,stock_saved=CASE WHEN default_stock_ng_ul IS NOT NULL OR default_resuspension_ul IS NOT NULL THEN 1 ELSE 0 END,yield_locked=1,stock_rules=NULL,concentration_basis=COALESCE(default_concentration_basis,'unknown')"+clause,ids or [])
        return cursor.rowcount


def apply_rules_to_records(ids,rules):
    """Atomically persist selected plans, preserving current yields and locks."""
    rules=InventoryRules.model_validate(rules).model_dump()
    ids=list(dict.fromkeys(ids))
    with store.connection() as db:
        db.execute('BEGIN IMMEDIATE')
        marks=','.join('?' for _ in ids)
        parts=[store.fragment_dict(row) for row in db.execute(
            f'SELECT * FROM fragments WHERE {store.ACTIVE_FRAGMENTS} AND id IN ({marks})',ids)]
        if len(parts)!=len(ids):
            raise LookupError('Selected fragment not found.')
        plans=resuspension_plan(parts,rules | {'resuspension_mode':'constrained','no_backbone':True})
        errors=[part['name']+': '+('; '.join(plan['warnings']) or 'No feasible plan')
            for part,plan in zip(parts,plans) if not plan['feasible']]
        if errors:
            raise ValueError(errors)
        encoded=json.dumps(rules)
        db.executemany("UPDATE fragments SET stock_ng_ul=?,resuspension_ul=?,stock_rules=?,stock_saved=1,concentration_basis='Custom rule plan (unmeasured)' WHERE id=?",
            [(plan['target_ng_ul'],plan['resuspension_ul'],encoded,part['id']) for part,plan in zip(parts,plans)])
    return len(parts)
