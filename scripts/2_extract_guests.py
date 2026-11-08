import re, json, collections
import pathlib; D=pathlib.Path(__file__).resolve().parent.parent/'data'/'intermediate'
eps=json.load(open(D/'raw.json'))
P=r"(?:van|de|der|den|ter|ten|te|het|'t|’t|von|al|el|du|le|la|da|di|op)"
W=r"[A-ZÀ-ÖØ-ÞĲ][\w'’]+(?:-[A-Za-zÀ-ÖØ-Þ][\w]+)*"
NAME=re.compile(rf"(?<![\w-])({W}(?:\s+(?:{P}\s+)*{W}){{1,3}})")
LEAD={'Met','Vaderlands','Waarom','Hoe','Heeft','Defensie','Over','Dr','Dr.','Theoloog','Wat','Is','Kan','De','Het','Dank','Tot','Geloven','Bestaat','Wordt','Aanval','Verlosser','Topwetenschapper','Schrijver','Journalist','Filosoof','Historicus','Hoogleraar','Psychiater','Cabaretier','Theologe','Socioloog','Bisschop','Rabbijn','Imam','Dominee','Pastor','Ds','Prof','Prof.','Kardinaal','Pater','Zuster','Broeder','Live','Q&A','Een','Deze','Ook','Zo','Als','Nu','Toen','En','Of','Maar','Dat','Die','In','Op','Bij','Na','Voor','Van','Waar','Wie','RTL-Z','Oud-premier','Minister','Premier','Paus','Generaal','Burgemeester','Kamerlid'}
BAD={'Nederland','Europa','God','Jezus','Bijbel','Trump','Amerika','Rusland','Oekraïne','Israël','Iran','China','Haag','Westen','Ongelooflijke','Best','Café','Tech','Wereldoorlog','Reset','Therapieland','Wereld','Russen','Bourgondiërs','Rotterdam','Europese','Midden-Oosten','Zwarte','Vinkjes','Correspondent','Vaticaan','Orbán','Hongarije','Poetin','Wilders','Islam','Kerk','Kerst','Pasen','Pinksteren','Geschiedenis','Oxford','Delft','JA21','AfD','Luther','Allah','Mohammed','Marx','Boeddha','Koran','Amsterdam','Vlaanderen','België','Duitsland','Frankrijk','Gaza','Palestina','Turkije','Afrika','Syrië','Elizabeth','Oranje','Aquino','Assisi','Franciscus','Biden','Musk','Peterson','Ellul','Nouwen','Kuyper','King','Holocaust','Bergrede','Romeinen','Grieken','Joden','Christus','Maria','Paulus','Mozes','Abraham','Petrus','Satan','Duivel','Hemel','Hel','Genesis','Openbaring','Kamer','Tweede','Eerste','The','Of','Ramadan','Sinterklaas','Nieuwe','Oude','Testament','Heilige',}
SUBJECT_PAT=['Donald Trump','Joe Biden','Elon Musk','Jordan Peterson','Jacques Ellul','Henri Nouwen','Abraham Kuyper','Thomas van Aquino','Paus Franciscus','Franciscus van Assisi','Queen Elizabeth','Willem van Oranje','Martin Luther King','Poetin','Wilders','Orbán','Vladimir Poetin','Karl Marx','Dietrich Bonhoeffer','C.S. Lewis','Augustinus','Nietzsche','Calvijn','Maarten Luther','Erasmus','Spinoza','Kierkegaard','Dostojevski']
HOSTS={'David Boogerd'}
def clean(n):
    toks=n.split()
    while toks and toks[0].strip(".'’") in LEAD: toks=toks[1:]
    n=' '.join(toks).strip(" '’-")
    n=re.sub(r"\s+van De Correspondent$","",n)
    if len(n.split())<2: return None
    if any(t.strip("'’") in BAD for t in n.split()): return None
    if n in SUBJECT_PAT: return None
    if not re.match(r"^[A-ZÀ-ÖØ-Þ]",n.split()[-1]): return None
    return n
def names_in(s):
    out=[]
    for m in NAME.findall(s):
        c=clean(m)
        if c and c not in out: out.append(c)
    return out
FIX={'Bea ten Tusscher':'Bea ten Tusscher','Iain McGilchrist':'Iain McGilchrist'}
known=collections.Counter()
for e in eps:
    e['g']=[n for n in names_in(e['t']) if n not in HOSTS]
    for n in e['g']: known[n]+=1
for e in eps:
    txt=e['t']+' '+e['desc']
    if not e['g']:
        e['g']=[n for n in names_in(e['desc']) if n in known and n not in HOSTS and n!='Stefan Paas'][:4]
        e['gsrc']='desc'
    e['paas']= ('Stefan Paas' in txt) or ('Paas' in e['t'])
    if 'Stefan Paas' in e['g']: e['g'].remove('Stefan Paas')
    e['subj']=[s for s in SUBJECT_PAT if s in txt]
zero=[e for e in eps if not e['g']]
print('zero',len(zero))
for e in zero: print(e['n'],e['t'][:110],'|',names_in(e['desc'])[:6])
json.dump(eps,open(D/'eps1.json','w'),ensure_ascii=False)
