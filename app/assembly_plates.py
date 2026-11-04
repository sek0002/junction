"""Destination plates and source-grouped transfers from calculated export rows."""
import csv
import io
import re
import math
from xml.sax.saxutils import escape

from .bench_exports import plate_key
from .exports import _safe_cell

TRANSFER_HEADERS = ['Source plate', 'Full source plate ID', 'Source well', 'Fragment / reagent', 'Type', 'Destination plate', 'Destination well', 'Assembly', 'Stage', 'Volume µL']
ASSIGNMENT_HEADERS = ['Plate', 'Well', 'Assembly', 'Stage', 'Enzyme', 'Total µL', 'Checks']


def layout(sections, export_day, identifier, url):
    """One physical reaction per well; nested stages remain separate reactions."""
    key = plate_key(sections)
    plates, transfers = [], []
    for index, section in enumerate(sections):
        page, offset = divmod(index, 96)
        if offset == 0:
            plates.append(dict(id=f'JUNC-{export_day.replace("-", "")}-{identifier.removeprefix("BL-")[:12].upper()}-P{page+1:02d}', wells=[]))
        plate = plates[page]
        well = f'{"ABCDEFGH"[offset//12]}{offset%12+1}'
        total = next((r['use'] for r in section['rows'] if r['kind'] == 'total'), None)
        issues = list(section['issues']) + [r['name']+': '+w for r in section['rows'] for w in r['checks']]
        checks = '; '.join(dict.fromkeys(issues)) or ('Pass' if section['valid'] else 'Check')
        assignment = dict(plate=plate['id'], well=well, name=section['name'], stage=section['stage'], enzyme=section['enzyme'], total=total, checks=checks)
        plate['wells'].append(assignment)
        for row in section['rows']:
            if row['kind'] == 'total':
                continue
            source = row.get('plate') or ''
            alias = key.get(source, {}).get('short') or ('Reagents' if row['kind'] == 'reagent' else 'Prepared' if str(row.get('id', '')).startswith('prepared:') else 'Unassigned')
            transfers.append([alias, source, row.get('well') or '', row['name'], row['kind'], plate['id'], well, section['name'], section['stage'], row['use']])
    def source_well(well):
        match=re.fullmatch(r'([A-Za-z]+)(\d+)',well)
        return (match[1].upper(),int(match[2])) if match else (well,0)
    transfers.sort(key=lambda row: (row[4]=='reagent',not bool(row[1]),row[0].casefold(), row[1].casefold(), source_well(row[2]), row[3].casefold(), row[5], 'ABCDEFGH'.index(row[6][0]), int(row[6][1:])))
    return dict(date=export_day, identifier=identifier, url=url, plates=plates, transfers=transfers)


def assignments(data):
    return [[w[k] for k in ('plate', 'well', 'name', 'stage', 'enzyme', 'total', 'checks')] for p in data['plates'] for w in p['wells']]


def csv_bytes(headers, rows):
    out = io.StringIO(newline=''); writer = csv.writer(out)
    writer.writerow(headers)
    for row in rows:
        writer.writerow([_safe_cell(f'{v:.2f}' if isinstance(v, float) else v) for v in row])
    return out.getvalue().encode('utf-8-sig')


def qr_png(url):
    # ReportLab supplies the QR encoder already used by the PDF runtime. No
    # network service receives worksheet URLs or nucleotide sequences.
    from PIL import Image, ImageDraw
    from reportlab.graphics.barcode.qrencoder import QRCode, QRErrorCorrectLevel
    qr = QRCode(None, QRErrorCorrectLevel.M); qr.addData(url); qr.make()
    size = qr.getModuleCount(); scale = 8; border = 4
    image = Image.new('RGB', ((size+2*border)*scale,)*2, 'white'); draw = ImageDraw.Draw(image)
    for y in range(size):
        for x in range(size):
            if qr.isDark(y, x):
                left, top = (x+border)*scale, (y+border)*scale
                draw.rectangle((left, top, left+scale-1, top+scale-1), fill='black')
    out = io.BytesIO(); image.save(out, 'PNG'); return out.getvalue()


def _font(size, bold=False):
    from PIL import ImageFont
    for name in (f'DejaVuSans{"-Bold" if bold else ""}.ttf', '/System/Library/Fonts/Supplemental/Arial.ttf'):
        try: return ImageFont.truetype(name, size)
        except OSError: pass
    return ImageFont.load_default(size=size)


def plate_png(data, plate):
    from PIL import Image, ImageDraw
    image = Image.new('RGB', (1200, 880), 'white'); draw = ImageDraw.Draw(image)
    dark = '#1D443B'; occupied = {w['well']: w for w in plate['wells']}
    draw.text((35, 25), plate['id'], font=_font(30, True), fill=dark)
    draw.text((35, 73), data['date']+' | 96 wells | '+str(len(occupied))+' reactions', font=_font(22), fill=dark)
    draw.text((35, 115), 'Download worksheet and plate maps', font=_font(20), fill=dark)
    qr = Image.open(io.BytesIO(qr_png(data['url']))); qr = qr.resize((175, 175), Image.Resampling.NEAREST)
    image.paste(qr, (995, 15))
    x0, y0, cw, ch = 72, 230, 91, 73
    for c in range(12): draw.text((x0+c*cw+30, y0-38), str(c+1), font=_font(23, True), fill=dark)
    for r, label in enumerate('ABCDEFGH'):
        draw.text((28, y0+r*ch+20), label, font=_font(23, True), fill=dark)
        for c in range(12):
            well=f'{label}{c+1}'; item=occupied.get(well); x,y=x0+c*cw,y0+r*ch
            draw.rounded_rectangle((x,y,x+cw-7,y+ch-7), radius=9, fill='#D8ECDD' if item else '#F4F6F5', outline='#86A395' if item else '#DDE4DF', width=2)
            if item:
                draw.text((x+8,y+6),well,font=_font(19,True),fill=dark)
                name=item['name']; name=name if len(name)<=10 else name[:4]+'…'+name[-5:]
                draw.text((x+5,y+37),name,font=_font(12),fill=dark)
    draw.text((35,842),'Junction | '+data['identifier'],font=_font(17),fill=dark)
    out=io.BytesIO();image.save(out,'PNG');return out.getvalue()


def append_excel(wb, data):
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.drawing.image import Image
    from openpyxl.utils import get_column_letter
    for index, plate in enumerate(data['plates'], 1):
        ws=wb.create_sheet(f'Plate map {index}'); ws.sheet_view.showGridLines=False
        ws['A1']=plate['id'];ws['A1'].font=Font(size=14,bold=True,color='1D443B')
        image=Image(io.BytesIO(plate_png(data,plate)));image.width=705;image.height=517;ws.add_image(image,'A3')
        ws['A35']=data['url'];ws['A35'].hyperlink=data['url'];ws['A35'].style='Hyperlink'
        ws['A36']='Date';ws['B36']=data['date'];ws['A37']='Export';ws['B37']=data['identifier']
        for c in range(1,13):ws.column_dimensions[get_column_letter(c)].width=8
        for r in range(3,35):ws.row_dimensions[r].height=12.5
        ws.print_area='A1:L38';_page(ws,1)
    for title,headers,rows,widths in [('Plate assignments',ASSIGNMENT_HEADERS,assignments(data),[39,7,32,24,16,11,28]),('Well transfers',TRANSFER_HEADERS,data['transfers'],[12,28,7,24,10,39,7,22,20,10])]:
        ws=wb.create_sheet(title);ws.append(headers)
        groups=list(dict.fromkeys(row[0] for row in data['transfers']))
        for row in rows:ws.append([_safe_cell(v) for v in row])
        for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='1D443B')
        hidden=('D','E','G') if title=='Plate assignments' else ('B','E','I')
        for column in hidden:ws.column_dimensions[column].hidden=True
        for r in range(2,ws.max_row+1):
            lines=1
            for cell in ws[r]:
                cell.font=Font(size=10);cell.alignment=Alignment(wrap_text=True,vertical='top')
                if isinstance(cell.value,(int,float)):cell.number_format='0.00'
                if cell.column_letter not in hidden:lines=max(lines,math.ceil(len(str(cell.value or ''))/max(5,widths[cell.column-1]-2)))
            ws.row_dimensions[r].height=max(24,lines*13+4)
            if title=='Well transfers':
                from .bench_exports import PALETTE
                color=PALETTE[groups.index(ws.cell(r,1).value)%len(PALETTE)]
                for c in (1,2):ws.cell(r,c).fill=PatternFill('solid',fgColor=color)
        for c,width in enumerate(widths,1):ws.column_dimensions[get_column_letter(c)].width=width
        ws.row_dimensions[1].height=32
        ws.freeze_panes='C2';ws.auto_filter.ref=ws.dimensions;ws.print_title_rows='1:1';ws.sheet_view.showGridLines=False
        _page(ws,0)


def _page(ws, height):
    ws.page_setup.orientation='portrait';ws.page_setup.paperSize=ws.PAPERSIZE_A4
    ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=height
    ws.page_margins.left=ws.page_margins.right=.25;ws.oddFooter.center.text='Junction | Page &P of &N'


def pdf_bytes(data, include_transfers=True, story_only=False):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Image, Spacer, PageBreak, LongTable, TableStyle
    out=io.BytesIO();small=ParagraphStyle('plate-cell',fontSize=8,leading=10);title=ParagraphStyle('plate-title',fontSize=14,leading=18)
    def p(value):return Paragraph(escape('—' if value is None else f'{value:.2f}' if isinstance(value,float) else str(value)),small)
    def table(headers, rows, widths):
        t=LongTable([[p(v) for v in headers]]+[[p(v) for v in row] for row in rows],colWidths=widths,repeatRows=1,splitInRow=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#D8ECDD')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F3F6F5')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),4),('RIGHTPADDING',(0,0),(-1,-1),4),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]));return t
    flow=[]
    for index,plate in enumerate(data['plates']):
        if index:flow.append(PageBreak())
        flow.extend([Paragraph(escape(plate['id']),title),Image(io.BytesIO(plate_png(data,plate)),width=540,height=396),Spacer(1,8),
                     Paragraph('<link href="'+escape(data['url'],{'"':'&quot;'})+'">Download worksheet and plate maps</link>',small),Spacer(1,10)])
        rows=[[w['well'],w['name'],w['stage'],w['total']] for w in plate['wells']]
        flow.append(table(['Well','Assembly','Stage','Total µL'],rows,[32,280,173,55]))
    if include_transfers:
        flow.extend([PageBreak(),Paragraph('Well transfers',title),Spacer(1,10)])
        for source in dict.fromkeys(row[0] for row in data['transfers']):
            rows=[row for row in data['transfers'] if row[0]==source]
            full=rows[0][1]
            flow.extend([Paragraph(escape(source+(' | '+full if full and full!=source else '')),title),Spacer(1,6)])
            values=[[r[2],r[3],r[5],r[6],r[7],r[9]] for r in rows]
            flow.extend([table(['Source well / '+source,'Fragment / reagent','Destination plate','Well','Assembly','µL'],values,[42,143,130,30,150,45]),Spacer(1,12)])
    if story_only:return flow
    SimpleDocTemplate(out,pagesize=A4,leftMargin=26,rightMargin=26,topMargin=24,bottomMargin=26,title=data['identifier']+' plate maps').build(flow)
    return out.getvalue()


def attach(content, format, data):
    if format=='xlsx':
        from openpyxl import load_workbook
        wb=load_workbook(io.BytesIO(content),rich_text=True);append_excel(wb,data);out=io.BytesIO();wb.save(out);return out.getvalue()
    if format=='pdf':
        # pypdf is deliberately not a runtime dependency; ReportLab renders the
        # worksheet and plate sections in one flow through assembly_matrix.
        raise ValueError('PDF plates are appended by the worksheet renderer')
    extra=io.StringIO(newline='');writer=csv.writer(extra);writer.writerow([]);writer.writerow(['Export']);writer.writerow(['Date','Identifier','Download']);writer.writerow([data['date'],data['identifier'],data['url']])
    writer.writerow([]);writer.writerow(['Plate assignments'])
    extra.write(csv_bytes(ASSIGNMENT_HEADERS,assignments(data)).decode('utf-8-sig'))
    writer.writerow([]);writer.writerow(['Well transfers'])
    extra.write(csv_bytes(TRANSFER_HEADERS,data['transfers']).decode('utf-8-sig'))
    return content+extra.getvalue().encode('utf-8')
