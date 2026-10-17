"""Read individual bibliographic card facts from public checklist formats.

Never collect user inventories, exchange statistics, descriptions or artwork.
Missing numbers are S/N, not invented numbering. Stable keys outlive row order.
"""
import hashlib
import io
import re
import unicodedata
from collections import Counter
from bs4 import BeautifulSoup
from pypdf import PdfReader

def norm(value):
    return ' '.join(unicodedata.normalize('NFKC',str(value or '')).split())

def number_key(value):
    value=norm(value)
    return str(int(value)) if value.isdigit() else value.casefold()

def row(number, name, section, team='', key=None):
    if not norm(name) or not norm(section):raise ValueError('missing_card_name_or_section')
    return {'n':int(number) if str(number).isdigit() and not str(number).startswith('0') else number,
        'original_identifier':number,'player':norm(name),'section':norm(section),
        'team':norm(team),'source_key':key or ('number:'+number_key(number) if number is not None
            else 'unnumbered:'+norm(section+'|'+name+'|'+team).casefold()),'parallels':[]}

def validate(cards):
    if not cards:raise ValueError('empty_checklist')
    keys=[c['source_key'] for c in cards]
    if len(keys)!=len(set(keys)):raise ValueError('duplicate_checklist_identity')
    return cards

def cromolista(raw):
    soup=BeautifulSoup(raw,'html.parser');section='Colección';cards=[]
    for element in soup.find_all(['h2','button']):
        if element.name=='h2':
            value=norm(element.get_text(' ',strip=True))
            if not re.fullmatch(r'Los \d+ cromos',value) and not value.startswith('Cambiar cromos de'):section=value
        elif element.has_attr('data-sin-cuenta'):
            item=element.find_parent('li');number=item.select_one('.num')
            label=item.select_one('span.min-w-0')
            if not number or not label:raise ValueError('changed_public_checklist_layout')
            n=norm(number.get_text());name=label.get_text(' ',strip=True)
            cards.append(row(n,name,section))
    return validate(cards)

def diramix(raw):
    soup=BeautifulSoup(raw,'html.parser');cards=[]
    for label in soup.find_all('label'):
        if not label.select_one('input.cards_mancanti'):continue
        number=label.select_one('.tc-label')
        if not number:raise ValueError('missing_official_sticker_number')
        n=norm(number.get_text())
        if not re.fullmatch(r'\d+|[A-Z]',n):raise ValueError('invalid_official_sticker_number')
        cards.append(row(n,'Cromo '+n,'Serie A–F' if n.isalpha() else 'Cromos'))
        cards[-1]['title_provided_by_source']=False
    return validate(cards)

def dragonball(raw):
    soup=BeautifulSoup(raw,'html.parser');cards=[];parallel=[]
    for fieldset in soup.find_all('fieldset'):
        legend=fieldset.find('legend')
        if not legend:continue
        section=norm(legend.get_text())
        for link in fieldset.select('.catalogo_coleccion_objeto a.divlink'):
            title=norm(link.get_text(' ',strip=True))
            match=re.fullmatch(r'Card (\d+)(?: \((.+)\))?',title)
            limited=re.fullmatch(r'Card Limitada (\d+) \((.+)\)',title)
            if limited:
                n,name=limited.groups();cards.append(row('LE '+n,name,'Ediciones limitadas'))
            elif match:
                n,variant=match.groups()
                if variant:
                    parallel.append((number_key(n),norm(variant)))
                else:cards.append(row(n,title,section))
            else:raise ValueError('unrecognized_dragonball_card:'+title)
    base={number_key(c['n']):c for c in cards if str(c['n']).isdigit()}
    for n,label in parallel:
        if n not in base:raise ValueError('parallel_without_base_card')
        if re.search(r'\d+\s*/\s*\d+|1/1|serial',label,re.I):continue
        base[n]['parallels'].append({'id':'variant-'+hashlib.sha256(label.casefold().encode()).hexdigest()[:16],
            'name':label,'serialized':False})
    return validate(cards)

def liga_f_pdf(raw):
    reader=PdfReader(io.BytesIO(raw));text='\n'.join(p.extract_text() or '' for p in reader.pages)
    if 'ALHAMA CF ELPOZO' not in text or 'ONCE PREMIUM' not in text:raise ValueError('wrong_liga_f_document')
    headers={'FOCUS (Resumen de la 24-25)','ENERGY MOEVE','FLOW','FEELING','FRESH','ONCE PREMIUM','MAXI PREMIUM'}
    lines=[norm(l) for l in text.splitlines() if norm(l)]
    teams={l for l in lines if l.upper()==l and not re.match(r'^\d',l)
        and l not in headers and l!='SERIES ESPECIALES'}
    cards=[];section='General';i=0
    while i<len(lines):
        line=lines[i];i+=1
        if line.startswith('No Nombre cromo') or line=='SERIES ESPECIALES':continue
        if line in teams or line in headers:section=line;continue
        m=re.match(r'^(\d+)(?:\s*([AB]))?\s+(.+)$',line)
        if m:
            n,letter,name=m.groups();n+=letter or ''
        elif section in {'ONCE PREMIUM','MAXI PREMIUM'}:
            n=None;name=line
        else:raise ValueError('unrecognized_liga_f_line:'+line)
        while i<len(lines) and not re.match(r'^\d+\s*(?:[AB]\s+)?',lines[i]) and lines[i] not in teams|headers and not lines[i].startswith('No ') and lines[i]!='SERIES ESPECIALES':
            # Premium cards each occupy their own line; other continuations are names/clubs.
            if n is None:break
            name+=' '+lines[i];i+=1
        team=section if section in teams else ''
        name=re.sub(r'\s+(PORTERA|DEFENSA|MEDIO|DELANTERA)$','',name)
        club=re.search(r'\s*\(([^)]+)\)$',name)
        if club:name,team=name[:club.start()].strip(),club[1]
        elif not team:
            for club_name in sorted(teams,key=len,reverse=True):
                title=club_name.title().replace(' Cf',' CF').replace(' Fc',' FC').replace(' Sd',' SD').replace(' Rcd',' RCD')
                if name.casefold().endswith(' '+title.casefold()):
                    name,team=name[:-len(title)].strip(),title;break
        name=re.sub(r'\s+(?:Capitana|Destacada)\b','',name)
        cards.append(row(n,name,section,team))
    if {int(re.match(r'\d+',str(c['n']))[0]) for c in cards if c['n'] is not None}!=set(range(1,381)):
        raise ValueError('liga_f_numbered_range_incomplete')
    return validate(cards)

def chicles_jr(raw):
    soup=BeautifulSoup(raw,'html.parser');article=soup.find('article')
    if not article or '2026-27' not in article.get_text():raise ValueError('wrong_chicles_edition')
    lines=[norm(l) for l in article.get_text('\n',strip=True).splitlines() if norm(l)]
    start=next(i for i,l in enumerate(lines) if l.startswith('LISTADO CROMOS CHICLES'))
    sections={'¡Vamos! (Escudos)','Masterclass','Box to Box','¿Quién es?'}
    section=None;cards=[]
    for line in lines[start+1:]:
        if line=='Categorías':break
        if line in sections:section=line;continue
        if not section:raise ValueError('missing_chicles_section')
        m=re.fullmatch(r'(.+?)\s*-\s*\((.+)\)',line)
        name,team=m.groups() if m else (line,line)
        cards.append(row(None,name,section,team,key='unnumbered:'+norm(section+'|'+team).casefold()))
    if Counter(c['section'] for c in cards)!={s:20 for s in sections}:raise ValueError('chicles_sections_incomplete')
    return validate(cards)

def extra_blog(raw):
    body=BeautifulSoup(raw,'html.parser').find(class_='post-body')
    if not body:raise ValueError('missing_checklist_body')
    lines=[norm(l) for l in body.get_text('\n',strip=True).splitlines() if norm(l)]
    # Join layout-wrapped facts before recognizing section headings / identifiers.
    lines=[re.sub(r'10 ca rds','10 cards',v) for v in lines]
    text='\n'.join(lines)
    text=re.sub(r'10 ca\nrds','10 cards',text)
    text=re.sub(r'(?m)^(GR 1\.)\n',r'\1 ',text)
    lines=text.splitlines()
    headings=['Squad Update','Manager','Away Kit',"UEFA Women's Champions League",'Wingman','Pitch Perfection',
        'Kings of Europe','Hat-Trick Hero','Topps Heritage - Man of the Match','Topps Heritage - Woman of the Match',
        "100 Club UEFA Women's Champions League",'100 Club Legend','100 Club','Clutch Kids','UEFA Official Matchball',
        'Match Attax Extra Title Card','UEFA 2026 Finals','Build-a-Baller Ultimate Baller','Black Edge Edition',
        'Chrome X','Infinity','D X-Lens Phase Shifter','X-Calibre','Limited Edition - Stadium Lights',
        'Limited Edition - ElectriX','Limited Edition - Untouchable','Limited Edition - Blitz Ballerz',
        'Limited Edition - Goaliaths','Limited Edition - Psykicks','Platinum Pull Limited Edition',
        'Gold Rush Ultra Limited Edition','X Greats Limited Edition','Black Fire Limited Edition','Royal Elite',
        'Facsimile Signature Style Pro View','Pro-View Original','UCL Decades Relic','Player-Worn Jersey Relic',
        'Genuine Autograph','Other Cards']
    start=lines.index('Squad Update');section='';cards=[];i=start
    while i<len(lines):
        line=lines[i];i+=1
        heading=next((h for h in headings if line.startswith(h)),None)
        if heading:
            section=heading
            continue
        if re.search(r'Genuine Autograph|Pro-View Original|Other Cards',line,re.I):
            section=line;continue
        match=re.match(r'^((?:[A-Z][A-Z0-9-]*(?: [A-Z]+)?(?: \d+)?|\d+))\.\s+(.+)$',line)
        if not match:continue
        if re.search(r'Genuine Autograph|Pro-View Original|Other Cards',section,re.I):continue
        n,name=match.groups()
        if i<len(lines) and lines[i].startswith('(') and ')' in lines[i]:name+=' '+lines[i];i+=1
        name=re.split(r'\s+-\s+(?:added|amended|thank)',name,flags=re.I)[0]
        name=re.sub(r'\s+#/\d+.*$','',name)
        club=re.search(r'\s*\(([^)]+)\)',name);team=club[1] if club else ''
        if club:name=name[:club.start()].strip()
        cards.append(row(n,name,section,team))
    if {int(c['n']) for c in cards if str(c['n']).isdigit()}!=set(range(1,320)):
        raise ValueError('extra_base_range_incomplete')
    return validate(cards)

def laststicker_text(raw):
    """Bibliographic facts from a public checklist rendering; discard all exchange statistics."""
    text=raw.decode('utf-8') if isinstance(raw,bytes) else raw
    facts={}
    for line in text.splitlines():
        match=re.fullmatch(r'(\d+|X\d+) (.+?) (\d+) (\d+) (\d+) ([\d.]+|—|-)',norm(line))
        if not match:continue
        n,description,*_=match.groups()
        if n in facts and facts[n]!=description:raise ValueError('conflicting_public_card_facts:'+n)
        facts[n]=description
    if not facts:raise ValueError('missing_individual_checklist_records')
    teams=[]
    for desc in facts.values():
        m=re.fullmatch(r'Team logo (.+) foil',desc)
        if m:teams.append(m[1])
    sections=sorted(teams+['Introduction','Key Players','Head To Head','2024-25 Awards',
        'EuroLeague 25 - All-25 Team','EuroLeague 25 - Final Four History'],key=len,reverse=True)
    cards=[]
    for n,description in facts.items():
        kind=re.search(r' (glow in the dark|glow-in-the-dark|holographic|figured|foil|-)$',description)
        if not kind:raise ValueError('changed_public_checklist_type:'+n)
        description=description[:kind.start()]
        section=next((s for s in sections if description.endswith(' '+s)),None)
        if section:
            name=description[:-len(section)].strip()
            name=re.sub(r'\)\s*[12]$',')',name)
            club=re.search(r'\(([^)]+)\)',name)
            team=club[1] if club else section if section in teams else ''
        elif description.endswith(' -'):
            name=description[:-2];section='Serie X' if n.startswith('X') else 'Cromos';team=''
        else:raise ValueError('changed_public_checklist_section:'+n)
        card=row(n,name,section,team)
        if kind[1]!='-':card['tag']=kind[1]
        if re.fullmatch(r'(?:Cromo|Sticker) \w+',name):card['title_provided_by_source']=False
        cards.append(card)
    return validate(cards)

def monopoly_text(raw):
    text=raw.decode('utf-8') if isinstance(raw,bytes) else raw
    start=text.index('### Base Checklist');end=text.index('### Related Posts',start)
    section='Base';cards=[]
    for line in text[start:end].splitlines():
        line=norm(line)
        if line.startswith('### '):section=line[4:].replace(' Checklist','');continue
        match=re.fullmatch(r'(\d+|BMB-\d+|WMB-\d+|[BWS]\d+) (.+)',line)
        if not match:continue
        n,name=match.groups()
        if name=='TBA' or name.startswith(('cards.','card.')):continue
        parts=name.rsplit(' - ',1);name=parts[0];team=parts[1] if len(parts)>1 else ''
        cards.append(row(n,name,section,team))
    if {int(c['n']) for c in cards if str(c['n']).isdigit()}!=set(range(1,101)):
        raise ValueError('monopoly_base_incomplete')
    return validate(cards)

def laststicker_html(raw):
    soup=BeautifulSoup(raw,'html.parser');lines=[]
    for tr in soup.select('tr'):
        cells=[norm(td.get_text(' ',strip=True)) for td in tr.find_all('td',recursive=False)]
        if len(cells)<8 or not re.fullmatch(r'\d+|X\d+',cells[0]):continue
        # Explicit public table columns only; do not retain the four exchange columns.
        lines.append(' '.join(cells[:4])+' 0 0 0 0')
    return laststicker_text('\n'.join(lines))

def monopoly_html(raw):
    soup=BeautifulSoup(raw,'html.parser')
    for header in soup.find_all(['h2','h3','h4']):header.replace_with('### '+norm(header.get_text(' ',strip=True)))
    return monopoly_text(soup.get_text('\n',strip=True))

PARSERS={'cromolista':cromolista,'diramix':diramix,'dragonball':dragonball,
    'liga_f_pdf':liga_f_pdf,'chicles_jr':chicles_jr,'extra_blog':extra_blog,
    'laststicker_html':laststicker_html,'monopoly_html':monopoly_html}
