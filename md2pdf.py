#!/usr/bin/env python3
"""
md2pdf.py  --  Render the project's Markdown documents to PDF (ReportLab).

Supports the subset used in this repo: '# ' title (+ centred subtitle lines
directly below it), '## ' / '### ' headings, paragraphs, '- ' and '1. '
lists, pipe tables, fenced code blocks, '> ' callouts, inline `code`,
**bold** and *italic*.  An optional first line
    <!-- footer: some text -->
sets the page footer.

Usage:  python3 md2pdf.py DOC.md [OUT.pdf]      (needs: pip install reportlab)
"""
import html, re, sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, ListFlowable, ListItem, Paragraph,
                                Preformatted, SimpleDocTemplate, Spacer, Table,
                                TableStyle)

NAVY  = colors.HexColor('#1F3A5F')
GREY  = colors.HexColor('#555555')
LIGHT = colors.HexColor('#E4E9F2')
RULE  = colors.HexColor('#C8CED8')
NOTE  = colors.HexColor('#EAF4EA')
NOTEB = colors.HexColor('#2E7D32')
CODEB = colors.HexColor('#F4F5F7')

S = {
    'title': ParagraphStyle('title', fontName='Helvetica-Bold', fontSize=22,
                            leading=27, alignment=TA_CENTER, textColor=NAVY,
                            spaceAfter=6),
    'sub':   ParagraphStyle('sub', fontName='Helvetica', fontSize=10.5,
                            leading=15, alignment=TA_CENTER, textColor=GREY),
    'h2':    ParagraphStyle('h2', fontName='Helvetica-Bold', fontSize=15,
                            leading=19, textColor=NAVY, spaceBefore=12,
                            spaceAfter=6),
    'h3':    ParagraphStyle('h3', fontName='Helvetica-Bold', fontSize=11,
                            leading=14, textColor=NAVY, spaceBefore=8,
                            spaceAfter=4),
    'body':  ParagraphStyle('body', fontName='Helvetica', fontSize=9.5,
                            leading=13.5, spaceAfter=5),
    'cell':  ParagraphStyle('cell', fontName='Helvetica', fontSize=8.5,
                            leading=11),
    'hcell': ParagraphStyle('hcell', fontName='Helvetica-Bold', fontSize=8.5,
                            leading=11),
    'note':  ParagraphStyle('note', fontName='Helvetica', fontSize=9.5,
                            leading=13.5, textColor=NOTEB),
    'code':  ParagraphStyle('code', fontName='Courier', fontSize=7.8,
                            leading=10),
}

def inline(text):
    """Markdown inline markup -> ReportLab paragraph markup."""
    text = html.escape(html.unescape(text), quote=False)
    parts = re.split(r'(`[^`]+`)', text)
    out = []
    for p in parts:
        if p.startswith('`') and p.endswith('`') and len(p) > 1:
            out.append(f'<font name="Courier">{p[1:-1]}</font>')
            continue
        p = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', p)
        p = re.sub(r'(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])', r'<i>\1</i>', p)
        out.append(p)
    return ''.join(out)

def table(rows, width):
    head, body = rows[0], rows[1:]
    data = [[Paragraph(inline(c), S['hcell']) for c in head]]
    data += [[Paragraph(inline(c), S['cell']) for c in r] for r in body]
    # column widths proportional to the longest cell text, clamped
    lens = [max(len(r[i]) if i < len(r) else 0 for r in rows) for i in range(len(head))]
    lens = [min(max(l, 8), 70) for l in lens]
    tot = sum(lens)
    t = Table(data, colWidths=[width * l / tot for l in lens], repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), LIGHT),
        ('GRID', (0, 0), (-1, -1), 0.5, RULE),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    return t

def boxed(flowable, bg, width):
    t = Table([[flowable]], colWidths=[width])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), bg),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    return t

def parse(md, width):
    lines = md.splitlines()
    footer = ''
    if lines and lines[0].startswith('<!-- footer:'):
        footer = lines.pop(0)[len('<!-- footer:'):].rstrip('-> ').strip()
    story, i = [], 0
    def is_block_start(l):
        return (l.startswith(('#', '- ', '|', '```', '>'))
                or re.match(r'\d+\. ', l) or not l.strip())
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1
        elif l.startswith('# '):
            story.append(Paragraph(inline(l[2:]), S['title']))
            i += 1
            while i < len(lines) and not lines[i].strip():
                i += 1
            while i < len(lines) and lines[i].strip():
                story.append(Paragraph(inline(lines[i]), S['sub']))
                i += 1
            story.append(Spacer(1, 8))
        elif l.startswith('## '):
            story.append(Paragraph(inline(l[3:]), S['h2']))
            i += 1
        elif l.startswith('### '):
            story.append(Paragraph(inline(l[4:]), S['h3']))
            i += 1
        elif l.startswith('```'):
            i += 1
            buf = []
            while i < len(lines) and not lines[i].startswith('```'):
                buf.append(lines[i])
                i += 1
            i += 1
            story.append(boxed(Preformatted('\n'.join(buf), S['code']), CODEB, width))
            story.append(Spacer(1, 6))
        elif l.startswith('>'):
            buf = []
            while i < len(lines) and lines[i].startswith('>'):
                buf.append(lines[i][1:].strip())
                i += 1
            story.append(boxed(Paragraph(inline(' '.join(buf)), S['note']), NOTE, width))
            story.append(Spacer(1, 6))
        elif l.startswith('|'):
            rows = []
            while i < len(lines) and lines[i].startswith('|'):
                cells = [c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?', c) for c in cells):
                    rows.append(cells)
                i += 1
            story.append(table(rows, width))
            story.append(Spacer(1, 6))
        elif l.startswith('- ') or re.match(r'\d+\. ', l):
            ordered = not l.startswith('- ')
            items = []
            while i < len(lines) and (lines[i].startswith('- ') or re.match(r'\d+\. ', lines[i])):
                txt = re.sub(r'^(- |\d+\. )', '', lines[i])
                i += 1
                while i < len(lines) and lines[i].startswith('  ') and lines[i].strip():
                    txt += ' ' + lines[i].strip()
                    i += 1
                items.append(ListItem(Paragraph(inline(txt), S['body']), leftIndent=14))
            if ordered:
                lf = ListFlowable(items, bulletType='1', bulletFormat='%s.',
                                  leftIndent=14, bulletFontName='Helvetica',
                                  bulletFontSize=9.5)
            else:
                lf = ListFlowable(items, bulletType='bullet', start='\u2022',
                                  leftIndent=14, bulletFontName='Helvetica',
                                  bulletFontSize=9.5, bulletOffsetY=-1)
            story.append(lf)
            story.append(Spacer(1, 3))
        else:
            buf = [l]
            i += 1
            while i < len(lines) and not is_block_start(lines[i]):
                buf.append(lines[i])
                i += 1
            story.append(Paragraph(inline(' '.join(buf)), S['body']))
    # keep a heading together with whatever follows it
    out = []
    for f in story:
        if out and isinstance(out[-1], Paragraph) and out[-1].style.name in ('h2', 'h3'):
            out[-1] = KeepTogether([out[-1], f])
        else:
            out.append(f)
    return out, footer

def main():
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else re.sub(r'\.md$', '', src) + '.pdf'
    md = open(src, encoding='utf-8').read()
    doc = SimpleDocTemplate(dst, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm)
    story, footer = parse(md, doc.width)
    title = re.search(r'^# (.+)$', md, re.M)
    doc.title = title.group(1) if title else ''
    doc.author = 'Firmware analysis'

    def on_page(canvas, d):
        canvas.saveState()
        canvas.setFont('Helvetica', 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(d.leftMargin, 10 * mm, footer)
        canvas.drawRightString(A4[0] - d.rightMargin, 10 * mm, f'Page {d.page}')
        canvas.restoreState()

    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f'wrote {dst}')

if __name__ == '__main__':
    main()
