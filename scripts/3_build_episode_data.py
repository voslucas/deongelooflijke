import json, re, collections
import pathlib; ROOT=pathlib.Path(__file__).resolve().parent.parent; D=ROOT/'data'/'intermediate'; OUTF=ROOT/'data'/'episodes.json'
eps=json.load(open(D/'eps1.json'))
REN={'NCTV Pieter-Jaap Aalbersberg':'Pieter-Jaap Aalbersberg','CDA-lijsttrekker Henri Bontenbal':'Henri Bontenbal','Koos-jan de Jager':'Koos-Jan de Jager'}
DROP={'de Nederlandse','Leo XIV','Charles III','Benedictus XVI','Adrianus VI'}
SUBJ_EXTRA={'Leo XIV':'Paus Leo XIV','Charles III':'Koning Charles III','Benedictus XVI':'Paus Benedictus XVI','Adrianus VI':'Paus Adrianus VI'}
MAN={216:["Tim 's Jongers"],79:['Hubert Smeets','Katya Tolstaya'],38:['Typhoon'],78:['Anonieme exorcist']}
ADD={313:['Typhoon']}
THEMES={
 'God & geloof':r'\bgod\b|geloof|gelovig|bidden|gebed|religie|religieus|spiritu',
 'Bijbel & Jezus':r'bijbel|jezus|evangeli|christus|bergrede|apostel|paulus',
 'Kerk & secularisatie':r'\bkerk|ontkerkelijk|seculari|paus|katholie|protestant|dominee|priester|klooster',
 'Islam & jodendom':r'islam|moslim|moskee|koran|jood|joden|joodse|jodendom|antisemit|imam|rabbijn',
 'Politiek':r'politiek|kamerlid|verkiezing|partij|premier|minister|democratie|populis|\bcda\b|\bpvv\b|\bvvd\b|kabinet',
 'Geopolitiek & oorlog':r'oorlog|rusland|poetin|oekraïne|navo|defensie|israël|gaza|midden-oosten|china|geopoliti|terror',
 'Amerika & Trump':r'trump|amerika|verenigde staten|\bvs\b|biden|evangelical',
 'Wetenschap & kosmos':r'wetenschap|kosmos|natuurkund|biolog|evolutie|hersenen|brein|neuro|oerknal|universum|dna',
 'Technologie & AI':r'\bai\b|kunstmatige intelligentie|technolog|smartphone|social media|algoritme|big tech|internet',
 'Filosofie & ethiek':r'filosof|ethiek|moraal|nietzsche|denker|vrije wil|waarheid',
 'Geschiedenis':r'geschiedenis|historic|historisch|middeleeuw|reformatie|eeuw\b|oudheid|romeinen',
 'Kunst & cultuur':r'kunst|muziek|roman|literatuur|schrijver|dichter|film|theater|cabaret|poëzie',
 'Zingeving & psyche':r'zingeving|depressie|angst|psych|eenzaam|geluk|burn-?out|therapie|leegte|mentale',
 'Dood & rouw':r'\bdood\b|sterven|rouw|verlies|euthanasie|hiernamaals|eeuwig leven',
 'Economie & geld':r'economie|geld|kapitalis|armoede|rijkdom|ongelijkheid|groei|consumptie',
 'Samenleving & migratie':r'migratie|vluchteling|racisme|identiteit|polarisatie|woke|samenleving|integratie',
 'Klimaat & natuur':r'klimaat|natuur|duurzaam|schepping|dieren|milieu',
 'Gezin & relaties':r'seks|huwelijk|gezin|ouderschap|kinderen|liefde|relatie|vrouw|feminis',
}
def fmt(t):
    tl=t.lower()
    if t=='Trailer': return 'Trailer'
    if 'best of' in tl: return 'Best Of'
    if 'café' in tl: return 'Café'
    if re.search(r'\(live\)|\blive\b',tl): return 'Live'
    if 'q&a' in tl: return 'Q&A'
    if 'geschiedenis #' in tl: return 'Spin-off'
    return 'Gesprek'
QUOTE=re.compile(r"[‘'“\"]([^‘’'“”\"]{40,220}?)[’'”\"]")
out=[]
for e in eps:
    g=[REN.get(x,x) for x in e['g'] if x not in DROP]
    subj=e['subj']+[v for k,v in SUBJ_EXTRA.items() if k in e['t']]
    if e['n'] in MAN: g=MAN[e['n']]
    g=g+[x for x in ADD.get(e['n'],[]) if x not in g]
    txt=(e['t']+' '+e['desc']).lower()
    th=[k for k,r in THEMES.items() if re.search(r,txt)]
    # rank themes by hits, keep top 4
    th=sorted(th,key=lambda k:-len(re.findall(THEMES[k],txt)))[:4]
    qs=[q.strip() for q in QUOTE.findall(e['desc']) if len(q.split())>=6][:3]
    out.append(dict(n=e['n'],t=e['t'],d=e['date'],s=e['secs'],x=e['desc'],r=e['rel'],id=e['npo'],sl=e['slug'],g=g,p=e['paas'],sj=sorted(set(subj)),th=th,f=fmt(e['title']),q=qs,mp3=e['mp3']))
# guest bios: sentence containing "<Name> is"
bios={}
for e in out:
    for name in e['g']:
        if name in bios: continue
        for sent in re.split(r'(?<=[.!?…])\s+|\n',e['x']):
            sent=sent.strip()
            if re.match(re.escape(name)+r"\s*(\([^)]*\))?,?\s*(is|was|werd)\b",sent) and len(sent)<320:
                bios[name]=sent.strip(); break
        if name not in bios:
            m=re.search(r"(?:met|spreekt|gesprek met)\s+((?:[a-zà-ÿ\-]+\s+){1,6})"+re.escape(name),e['x'])
            if m and len(m.group(1))>6 and not re.search(r'\b(daarover|we|wij|david|gesprek|hij|zij|ze|ook|nu|die|dat|het|een|aflevering)\b',m.group(1)): bios[name]=(m.group(1).strip().capitalize()+'.')
bios['Stefan Paas']='Theoloog, hoogleraar aan de Vrije Universiteit Amsterdam en de Theologische Universiteit Utrecht, en vaste gast van De Ongelooflijke.'
bios['David Boogerd']='Journalist en presentator van De Ongelooflijke Podcast sinds de eerste aflevering in april 2019.'
json.dump(dict(eps=out,bios=bios,built='2026-11-07'),open(OUTF,'w'),ensure_ascii=False,separators=(',',':'))
import os; print(os.path.getsize(OUTF), len(bios), collections.Counter(e['f'] for e in out), collections.Counter(t for e in out for t in e['th']).most_common(), sum(len(e['q']) for e in out), sum(e['p'] for e in out))
for k in list(bios)[:12]: print(k,'::',bios[k][:160])
D=json.load(open(OUTF))
D['bios'].update({
 'Beatrice de Graaf':'Historicus en hoogleraar aan de Universiteit Utrecht; “vriendin van de show” en met Stefan Paas het duo achter spin-off De Ongelooflijke Geschiedenis.',
 'Joris Luyendijk':'Schrijver en antropoloog.',
 'Arjen Lubach':'Presentator, cabaretier, dj, schrijver én overtuigd atheïst — gast van de allereerste aflevering.',
 'Typhoon':'Rapper Typhoon (Glenn de Randamie).',
 'Anonieme exorcist':'Een priester die door het Vaticaan is opgeleid als exorcist; hij doet zijn verhaal anoniem.'})
json.dump(D,open(OUTF,'w'),ensure_ascii=False,separators=(',',':'))
