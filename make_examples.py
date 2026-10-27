"""Generate printable inventory and recipe workbooks from the active database."""
import csv
import json
from pathlib import Path

from app.main import seed_examples, recipes, AssemblyRequest, ReactionSettings, build, inventory_plan
from app import database
from app.exports import make_workbook, genbank_bytes


def main():
    seed_examples()
    output=Path(__file__).resolve().parent/'printable_examples'
    output.mkdir(exist_ok=True)
    inventory=database.fragments()
    settings=ReactionSettings(backbone_pmol=.05,insert_ratio=1,resuspension_mode='constrained',
        preferred_resuspension_ul=50,max_resuspension_ul=99.99,min_input_volume_ul=1,max_input_volume_ul=5,
        no_backbone=True)
    planned=inventory_plan(settings)
    (output/f'Resuspension_reference_all_{len(inventory)}_fragments.xlsx').write_bytes(
        make_workbook(inventory,settings=planned['settings']))
    reference=[]
    for f,plan in zip(inventory,planned['rows']):
        reference.append({'Name':f['name'],'Plate identifier':f['plate_id'],'Well':f['well'],
            'Physical length bp':f['physical_length'],'Delivered yield ng':f['yield_ng'],
            'Planned stock ng per uL':round(plan['target_ng_ul'],6) if plan['target_ng_ul'] is not None else '',
            'Planned solvent uL':round(plan['resuspension_ul'],6) if plan['resuspension_ul'] is not None else '',
            'Planned input uL':plan['input_volume_ul'],'Planned fmol':round(plan['target_fmol'],6) if plan['target_fmol'] is not None else '',
            'Molar ratio':settings.insert_ratio,'Backbone':'No backbone',
            'Target pmol per DNA input':settings.backbone_pmol,
            'Feasible':plan['feasible'],'Feasibility':plan['feasibility'],
            'Measured stock ng per uL':f['stock_ng_ul'] or '',
            'Basis':'Proposed constrained stock; not measured',
            'Measured stock basis':f['concentration_basis'] if f['stock_ng_ul'] else '',
            'Checks':'; '.join(plan['warnings'])})
    with (output/'Resuspension_reference_numeric.csv').open('w',newline='') as handle:
        w=csv.DictWriter(handle,fieldnames=list(reference[0]));w.writeheader();w.writerows(reference)
    summary=[]
    for recipe in recipes():
        if not recipe['available']:
            continue
        name=recipe['name'].replace(' · ','_')
        payload=AssemblyRequest(name=name,enzyme=recipe['enzyme'],starter_fragment_id=None,circular=None,
            fragment_ids=recipe['no_backbone_fragment_ids'],settings={'backbone_pmol':.05,'insert_ratio':1,
            'resuspension_mode':'constrained','preferred_resuspension_ul':50,'max_resuspension_ul':99.99,
            'min_input_volume_ul':1,'max_input_volume_ul':5,'assume_target_stock':True,'no_backbone':True})
        result,physical=build(payload)
        assert result['valid'],result['errors']
        assert result['circular'] and result['circular_detected']
        assert all(part['role']=='insert' for part in physical)
        assert all(abs(row['target_fmol']-50)<1e-9 for row in result['reaction']['rows'])
        assert result['reaction']['water_ul'] is not None
        result['parts']=physical
        (output/(name+'_assembly_worksheet.xlsx')).write_bytes(make_workbook(inventory,result,result['effective_settings']))
        (output/(name+'.gb')).write_bytes(genbank_bytes(name,result['sequence'],result['features'],circular=result['circular'],notes=result['warnings']))
        (output/(name+'_reaction.json')).write_text(json.dumps(result['reaction'],indent=2))
        summary.append({'name':name,'length':result['length'],'circular':result['circular'],
            'circular_detected':result['circular_detected'],'fragment_count':len(physical),
            'no_backbone':result['effective_settings']['no_backbone'],
            'pmol_per_DNA_input':payload.settings.backbone_pmol,
            'insert_ratio':payload.settings.insert_ratio,'resuspension_mode':payload.settings.resuspension_mode,
            'planned_input_range_ul':[min(row['volume_ul'] for row in result['reaction']['rows']),max(row['volume_ul'] for row in result['reaction']['rows'])],
            'planning_reference':result['effective_settings']['backbone_reference'],
            'water_ul':result['reaction']['water_ul'],'warnings':result['warnings']+result['reaction']['warnings']})
    (output/'README.txt').write_text('All workbooks use the active delivered plate maps. These examples use No backbone: every selected fragment is a DNA input at 0.05 pmol (50 fmol) per reaction, with a 1:1 molar ratio and 1–5 uL per input. F1 is an ordinary fragment; no fragment supplies a backbone mass or length reference. Required mass for each input = 50 fmol × its full physical bp × 660 / 1,000,000; synthesis adapters and buffers are included. Each of the four example assemblies closes into a circular plasmid by matching its terminal overhangs. Resuspension volumes prefer 50 uL, are adjusted within each mass-dependent feasible interval, rounded safely to 0.01 uL, and remain below 100 uL (99.99-uL cap). Unavailable or infeasible plans are flagged, never filled with a fabricated stock. Actual stock concentrations are not inferred or saved. Example assembly worksheets explicitly allow proposed concentrations; measured stock overrides them and is checked against the 1–5-uL input limits. Review total reaction volume and any overfill warning. The Resuspension plan sheet and numeric CSV are computed export snapshots for immediate printing. Resuspension inventory and Assembly pipetting contain editable formulas; recalculate them in Excel after changing settings.\n')
    (output/'example_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({'fragments':len(inventory),'workbooks':len(summary)+1,'assembly_examples':summary},indent=2))


if __name__=='__main__':
    main()
