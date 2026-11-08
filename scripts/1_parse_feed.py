import re, json, html, sys
from xml.etree import ElementTree as ET
from email.utils import parsedate_to_datetime
ns={'itunes':'http://www.itunes.com/dtds/podcast-1.0.dtd'}
t=ET.parse(sys.argv[1]); ch=t.getroot().find('channel')
marks=['We gaan weer live','🔎','📜','📱','📺','🏛','Relevante afleveringen','🎧','Volg De Ongelooflijke','Volg ons']
eps=[]
for it in ch.findall('item'):
    g=lambda s: (it.findtext(s,'',ns) or '').strip()
    raw=g('description') or g('itunes:summary')
    txt=html.unescape(re.sub(r'<[^>]+>',' ',raw))
    txt=re.sub(r'[ \t\r\f\v]+',' ',txt)
    cut=len(txt)
    for m in marks:
        i=txt.find(m)
        if 0<=i<cut: cut=i
    rel=sorted(set(int(x) for x in re.findall(r'🎧\s*#(\d+)',txt)))
    body=re.sub(r'\s*\(https?:[^)]+\)','',txt[:cut]).strip()
    body=re.sub(r'\s*\n\s*','\n',body)
    d=parsedate_to_datetime(g('pubDate'))
    dur=g('itunes:duration'); p=[int(x) for x in dur.split(':')] if dur else [0]
    secs=sum(v*60**i for i,v in enumerate(reversed(p)))
    enc=it.find('enclosure'); url=enc.get('url') if enc is not None else ''
    m=re.search(r'/file/de-ongelooflijke-podcast/(\d+)/([^?.]+)',url)
    n=g('itunes:episode')
    title=g('title')
    tn=re.match(r'#\s*(\d+)\s*[-–:]?\s*(.*)',title)
    eps.append(dict(n=int(n) if n else (int(tn.group(1)) if tn else None), title=title, t=tn.group(2) if tn else title, date=d.date().isoformat(), secs=secs, desc=body, rel=rel, npo=m.group(1) if m else '', slug=m.group(2) if m else '', mp3=url.split('?')[0]))
import pathlib; OUT=pathlib.Path(__file__).resolve().parent.parent/'data'/'intermediate'; OUT.mkdir(parents=True,exist_ok=True)
json.dump(eps,open(OUT/'raw.json','w'),ensure_ascii=False,indent=0)
print(len(eps), sum(1 for e in eps if e['n'] is None))
