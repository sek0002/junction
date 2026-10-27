"""Display labels preserve the full inventory identifiers as source data."""
from collections import Counter
import re


def plate_label(identifier):
    value=str(identifier or '')
    match=re.match(r'^pSHPs(.*)',value,re.IGNORECASE)
    return (''.join(c for c in match[1] if c.isalnum())[:4] or value) if match else value


def plate_aliases(identifiers):
    plates=sorted({str(p) for p in identifiers if p})
    bases={p:plate_label(p) for p in plates}
    counts=Counter(bases.values());seen=Counter();used=set();result={}
    for plate in plates:
        short=bases[plate]
        if counts[short]>1:
            seen[short]+=1;short+='-'+str(seen[short])
        while short in used:short+='*'
        used.add(short);result[plate]=short
    return result


def label_workbook_plates(workbook):
    """Shorten table plate cells; retain exact identifiers in cell comments."""
    from openpyxl.comments import Comment
    cells=[]
    for sheet in workbook:
        for row in sheet.iter_rows(min_row=1,max_row=min(5,sheet.max_row)):
            if not any(cell.value=='Well' for cell in row):continue
            for header in row:
                if header.value not in ('Plate','Plate identifier','Plate ID'):continue
                cells.extend(sheet.cell(r,header.column) for r in range(header.row+1,sheet.max_row+1)
                             if isinstance(sheet.cell(r,header.column).value,str) and sheet.cell(r,header.column).value)
    aliases=plate_aliases(cell.value for cell in cells)
    for cell in cells:
        original=cell.value;short=aliases[original]
        if short!=original:
            cell.value=short;cell.comment=Comment(original,'Full plate ID')
