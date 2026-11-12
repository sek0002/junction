"""Printable comparison results; no sequences or database writes are required."""
import io
from datetime import datetime,timezone
from openpyxl import Workbook
from openpyxl.styles import PatternFill,Font

from .exports import _format_sheet,_safe_cell
from .plate_labels import label_workbook_plates
from .comparison_metrics import AT_DELETION_POLICY


def exact_match(match):
    return (match.get('exact') is True and match.get('identity')==1 and match.get('coverage',1)==1
            and match.get('reference_coverage',1)==1 and match.get('query_coverage',1)==1)


def match_type(match):
    if exact_match(match):
        return 'True 100%'
    if match.get('adjusted_identity')==1:
        return 'Adjusted 100%'
    return ''


def span_text(spans):
    return '; '.join(f'{int(a)+1}–{int(b)}' if a!=b else f'gap after {int(a)}' for a,b in spans)


def comparison_workbook(records,scope):
    chosen=[]
    for record in records:
        matches=record.get('matches') or []
        perfect=next((m for m in matches if match_type(m)),None)
        if scope=='exact' and (record.get('error') or perfect is None):continue
        chosen.append((record,perfect or (matches[0] if matches else {})))
    if not chosen:raise ValueError('No results match the export selection.')
    if sum(len(r.get('fragment_matches',[]))+len(m.get('changes',[]))+sum(len(region.get('effects',[])) for region in m.get('coding_analysis',{}).get('regions',[])) for r,m in chosen)>100000:
        raise ValueError('Select fewer files; this export exceeds 100,000 detail rows.')
    wb=Workbook();results=wb.active;results.title='Results'
    results.append(['File','Record','Query bp','Topology','Closest match','Source','Reference bp','True identity %','Adjusted identity %','100% match',
                    'Strand','Query rotation','Substituted bp','Inserted bp','Deleted bp','Fragments','Exact fragments','Enzymes','Aliases','Status',
                    'True reference coverage %','Adjusted reference coverage %','True query coverage %','Adjusted query coverage %','Aligned bp','Excluded A/T deletion bp','Adjustment rule','Match type','Coding regions','Coding effects','Synonymous substitutions','Frameshift regions'])
    fragments=wb.create_sheet('Fragments');fragments.append(['File','Record','Reference','Fragment','Plate','Well','Representation','Query positions (1-based)','Strand','True identity %','Adjusted identity %','True coverage %','Adjusted coverage %','100% match','Status','Excluded A/T deletion bp','Adjustment rule','Match type'])
    changes=wb.create_sheet('Differences');changes.append(['File','Record','Reference','Type','Reference positions (1-based)','Original query positions (1-based)','Reference bases','Query bases','Excluded from adjusted percentages','Coding effects'])
    regions=wb.create_sheet('Coding regions');regions.append(['File','Record','Reference','Region','Basis','Annotation source','Reference frame','Query frame','codon_start','Translation table','Reference aa','Query aa','Protein changed','Frameshift','Reference positions','Original query positions','Warnings','Reference translation','Query translation'])
    coding=wb.create_sheet('Coding changes');coding.append(['File','Record','Reference','Region','Basis','Effect','Reference positions','Original query positions','Reference codon','Query codon','Reference aa','Query aa','Reference aa position','Query aa position','Protein change','Translation table'])
    def append(sheet,row):sheet.append([_safe_cell(v) for v in row])
    def percentage(match,adjusted,original):
        value=match.get(adjusted,match.get(original))
        return value*100 if value is not None else None
    for record,match in chosen:
        filename=record.get('filename','');name=record.get('query_name','');hits=record.get('fragment_matches') or []
        diffs=match.get('changes') or [];identity=match.get('identity')
        counts={kind:sum(len(c.get('query_bases' if kind=='insertion' else 'reference_bases','')) for c in diffs if c.get('type')==kind) for kind in ('substitution','insertion','deletion')}
        detection=record.get('enzyme_detection') or {}
        report=match.get('coding_analysis') or record.get('query_coding_analysis') or {}
        coding_regions=report.get('regions',[])
        coding_effects=[effect for region in coding_regions for effect in region.get('effects',[])]
        append(results,[filename,name,record.get('query_length'), 'Circular' if record.get('query_circular') else 'Linear',match.get('name',''),match.get('source',''),match.get('reference_length'),
                        identity*100 if identity is not None else None,percentage(match,'adjusted_identity','identity'),'Yes' if match_type(match) else 'No',match.get('orientation',''),match.get('rotation'),
                        counts['substitution'],counts['insertion'],counts['deletion'],len(hits),sum(exact_match(h) for h in hits),
                        '; '.join(detection.get('compatible_assembly_modes') or detection.get('tested') or []),
                        '; '.join(a.get('name','') for a in match.get('aliases',[])),record.get('error') or ('Exact' if exact_match(match) else 'Adjusted 100% match' if match_type(match) else 'Near match' if match else 'No assembly match'),
                        match['reference_coverage']*100 if match.get('reference_coverage') is not None else None,
                        percentage(match,'adjusted_reference_coverage','reference_coverage'),
                        match['query_coverage']*100 if match.get('query_coverage') is not None else None,
                        percentage(match,'adjusted_query_coverage','query_coverage'),match.get('aligned_bp'),match.get('excluded_at_deletion_bp',0),match.get('at_deletion_policy',AT_DELETION_POLICY),match_type(match),
                        len(coding_regions),sum(effect['type']!='synonymous' for effect in coding_effects),sum(effect['type']=='synonymous' for effect in coding_effects),sum(region.get('frameshift',False) for region in coding_regions)])
        for hit in hits:
            append(fragments,[filename,name,match.get('name',''),hit.get('name',''),hit.get('plate_id',''),hit.get('well',''),hit.get('representation',''),span_text(hit.get('query_spans',[])),
                             hit.get('strand',''),hit.get('identity',0)*100,percentage(hit,'adjusted_identity','identity'),hit.get('coverage',0)*100,
                             percentage(hit,'adjusted_reference_coverage','coverage'),'Yes' if match_type(hit) else 'No',hit.get('status',''),hit.get('excluded_at_deletion_bp',0),hit.get('at_deletion_policy',AT_DELETION_POLICY),match_type(hit)])
        for change in diffs:
            consequences='; '.join(effect['region_name']+': '+effect['type'].replace('_',' ')+' '+effect.get('protein_change','') for effect in change.get('coding_effects',[]))
            append(changes,[filename,name,match.get('name',''),change.get('type',''),span_text([[change.get('reference_start',0),change.get('reference_end',0)]]),span_text(change.get('original_query_spans',[])),change.get('reference_bases',''),change.get('query_bases',''),'Yes' if change.get('excluded_from_adjusted_percentages') else 'No',consequences])
        for region in coding_regions:
            basis='Predicted ORF' if region['basis']=='predicted_orf' else 'Annotated CDS'
            changed=region.get('protein_changed')
            append(regions,[filename,name,match.get('name',''),region['name'],basis,region['source'],region.get('reference_frame'),region.get('query_frame'),region['codon_start'],region['translation_table'],region['reference_aa_length'],region['query_aa_length'],
                            'Review' if changed is None else 'Yes' if changed else 'No','Yes' if region.get('frameshift') else 'No',span_text(region['reference_spans']),span_text(region['query_spans']),'; '.join(region['warnings']),region['reference_protein'],region['query_protein']])
            for effect in region['effects']:
                append(coding,[filename,name,match.get('name',''),region['name'],basis,effect['type'].replace('_',' '),span_text(effect['reference_spans']),span_text(effect['query_spans']),effect['reference_codon'],effect['query_codon'],effect['reference_aa'],effect['query_aa'],effect['amino_acid_position'],effect['query_amino_acid_position'],effect['protein_change'],region['translation_table']])
    metadata=wb.create_sheet('Export');metadata.append(['Setting','Value'])
    metadata.append(['Selection','100% true or adjusted matches' if scope=='exact' else 'Selected files'])
    metadata.append(['Records',len(chosen)])
    metadata.append(['Exported (UTC)',datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')])
    metadata.append(['Coordinates','1-based, inclusive; gap positions are between bases. Query coordinates refer to the original uploaded sequence.'])
    metadata.append(['Identity','Identical alignment columns / all alignment columns, including gaps. Exact requires the exact-match flag and identity 1.'])
    metadata.append(['100% matches','Includes true exact matches and adjusted identity equal to 100%. Match type identifies which criterion qualified each result.'])
    metadata.append(['Adjusted percentages',AT_DELETION_POLICY+' are removed from identity and reference-coverage denominators. True percentages and all differences are retained. An adjusted 100% does not mark a true exact match.'])
    metadata.append(['Coverage','Paired reference/query bases, including substitutions but excluding gaps, divided by reference/query length respectively. Full coverage alone is not an exact match.'])
    metadata.append(['Scope','One closest reference per record; fragments can overlap. Not detected is not proof of absence.'])
    metadata.append(['Coding analysis','Annotated CDS uses biological strand/join order, codon_start and transl_table. Without CDS annotations, predicted ATG-to-stop ORFs of at least 30 aa are scanned on six frames. All true gaps are retained for coding consequences.'])
    for sheet,widths in [(results,[28,28,12,14,35,24,14,14,18,14,10,14,16,14,14,12,15,25,45,35,19,22,19,22,14,20,55,20,16,16,20,18]),(fragments,[28,28,32,30,25,9,25,30,10,14,18,14,18,14,20,20,55,20]),(changes,[28,28,32,16,26,30,45,45,24,55]),(regions,[28,25,30,28,20,18,16,16,14,18,14,14,18,14,28,28,55,60,60]),(coding,[28,25,30,28,20,22,26,26,18,18,14,14,18,18,22,18]),(metadata,[24,95])]:
        _format_sheet(sheet,widths,paper='A3' if sheet==results else 'A4');sheet.oddFooter.right.text='Junction comparison'
    for column in (7,8):
        for row in range(2,regions.max_row+1):regions.cell(row,column).number_format='+0;-0'
    for sheet,column in ((results,10),(fragments,14)):
        for row in range(2,sheet.max_row+1):
            if sheet.cell(row,column).value=='Yes':
                cell=sheet.cell(row,column);cell.fill=PatternFill('solid',fgColor='E9F3EE');cell.font=Font(name='Aptos',size=10,bold=True,color='176C58')
    for sheet,columns in ((results,(8,9,21,22,23,24)),(fragments,(10,11,12,13))):
        for col in columns:
            for row in range(2,sheet.max_row+1):sheet.cell(row,col).number_format='0.0000'
    label_workbook_plates(wb)
    output=io.BytesIO();wb.save(output);return output.getvalue()
