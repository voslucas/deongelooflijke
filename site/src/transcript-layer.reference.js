
// ---------- transcript layer (VOORBEELDDATA) ----------
// Everything below is shaped like the output of a real transcript pipeline
// (segments with speaker + start/end, laughs, mentions). Until real transcripts exist,
// segments are the episode description split into sentences, and all times and counts
// come from a seeded random generator so they stay stable between visits.
function hashStr(s){let h=2166136261;for(let i=0;i<s.length;i++){h^=s.charCodeAt(i);h=Math.imul(h,16777619)}return h>>>0}
function rng(seed){let a=hashStr(String(seed));return()=>{a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}}
const ts=s=>{s=Math.max(0,Math.round(s));const h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return (h?h+':'+String(m).padStart(2,'0'):m)+':'+String(x).padStart(2,'0')};
const pickN=(r,arr,n)=>{const a=[...arr],out=[];while(out.length<n&&a.length)out.push(a.splice(Math.floor(r()*a.length),1)[0]);return out};
const TICS=['eigenlijk','zeg maar','nou','weet je','in die zin','als het ware','precies','interessant'];
const THINKERS=['Augustinus','Charles Taylor','Nietzsche','Kierkegaard','Dietrich Bonhoeffer','C.S. Lewis','Calvijn','Maarten Luther','Blaise Pascal','Tom Holland','Spinoza','Dostojevski','Simone Weil','Thomas van Aquino','Hannah Arendt','René Girard'];
const BIBLE=['Genesis 1','Genesis 22','Exodus 3','Psalm 23','Psalm 139','Prediker 3','Jesaja 53','Matteüs 5','Matteüs 25','Lucas 15','Johannes 1','Johannes 3','Romeinen 8','1 Korintiërs 13','Openbaring 21'];
const BINGO=['“Dat is een goede vraag”','Secularisatie','Charles Taylor','“Even terug naar…”','Bijbelcitaat','Gelach om Stefan','“In die zin”','Augustinus','“Wat bedoel je precies?”'];
const SPC={host:'var(--ink)',paas:'var(--gold-deep)',g:['var(--violet)','var(--teal)','var(--rose)']};
function personBase(name){const r=rng('p'+name);return {wpm:Math.round(138+r()*46),tic:TICS[Math.floor(r()*TICS.length)]}}
const CUR={
 327:{tldr:'Kader Abdolah groeide op in een islamitische familie in Iran, werd marxist en revolutionair, vluchtte naar Nederland en vertaalde later de Koran. Nu schreef hij een boek over Jezus. Met David Boogerd en Stefan Paas praat hij over waarom hij niet wilde sterven zonder Jezus écht te hebben leren kennen.',
  points:['In het ouderlijk huis stond een Bijbel die niemand aanraakte: ‘een soort verboden boek’.','Als jonge man waren Castro en Che Guevara zijn helden; zijn verzet tegen het regime dwong hem te vluchten.','Met een paar honderd woordjes uit Jip en Janneke begon hij in het Nederlands te schrijven.','Een ontmoeting met paus Benedictus XVI zette hem op het spoor van zijn boek Jezus.'],
  chapters:['Een verboden boek in de bibliotheek','Van marxist tot vluchteling','Schrijven met woordjes uit Jip en Janneke','De paus die zijn werk las','Een boek over Jezus','Knielen bij de kribbe']}
};
function mkTitle(s){s=s.replace(/^[‘'"“]+/,'');const q=s.match(/^[^?]{10,80}\?/);if(q)return q[0];const c=s.split(/[,;:–—]/)[0].trim();return c.length>72?c.slice(0,70).replace(/\s+\S*$/,'')+'…':c.replace(/\.$/,'')}
const TX={};
function transcriptFor(e){
  if(TX[e.key])return TX[e.key];
  const r=rng('e'+e.key),D=e.s,cur=CUR[e.n]||{};
  const spk=[{name:'David Boogerd',role:'Presentator',c:SPC.host}];
  if(e.p)spk.push({name:'Stefan Paas',role:'Vaste gast',c:SPC.paas});
  e.g.slice(0,3).forEach((g,i)=>spk.push({name:g,role:'Gast',c:SPC.g[i]}));
  const guests=spk.filter(s=>s.role==='Gast'),paas=spk.find(s=>s.role==='Vaste gast');
  let sents=e.x.split(/\n|(?<=[.!?…’])\s+(?=[A-ZÀ-Þ‘'"“])/).map(s=>s.trim()).filter(s=>s.length>18);
  if(!sents.length)sents=[e.t];
  const segs=sents.map((t,i)=>{const q=/\?[’'"”]?$/.test(t);let sp;
    if(i===0||(q&&r()<.75))sp=spk[0];
    else if(paas&&r()<(guests.length?.3:.85))sp=paas;
    else sp=guests.length?guests[Math.floor(r()*guests.length)]:(paas||spk[0]);
    return {sp,t,w:t.split(/\s+/).length*(sp===spk[0]?.55:1.5)*(.6+r()*.8)}});
  const tw=segs.reduce((a,s)=>a+s.w,0);let c0=D*.012;
  segs.forEach((s,i)=>{s.i=i;s.start=c0;s.dur=s.w/tw*D*.975;c0+=s.dur;s.end=c0});
  spk.forEach(s=>{const b=personBase(s.name),mine=segs.filter(x=>x.sp===s);
    s.time=mine.reduce((a,x)=>a+x.dur,0);s.share=s.time/D;s.wpm=Math.round(b.wpm+(r()-.5)*16);s.words=Math.round(s.time/60*s.wpm);
    s.turns=mine.length;s.longestSeg=mine.sort((a,b)=>b.dur-a.dur)[0]||null;s.longest=s.longestSeg?s.longestSeg.dur:0;
    s.ttr=+(.3+r()*.17).toFixed(2);s.tics={};TICS.forEach(t=>s.tics[t]=Math.floor(r()*r()*12*Math.max(.25,s.share*2.5)));s.tics[b.tic]+=4+Math.floor(r()*14*Math.max(.35,s.share*2));
    s.questions=s.role==='Presentator'?Math.round(16+r()*36*D/4500):Math.round(r()*7)});
  const k=Math.max(2,Math.min(6,Math.round(segs.length/3)));const per=segs.length/k;
  const chapters=[...Array(k)].map((_,j)=>{const g=segs.slice(Math.round(j*per),Math.round((j+1)*per));if(!g.length)return null;const lead=g.find(x=>x.sp!==spk[0])||g[0];
    return {j,start:j===0?0:g[0].start,end:g.at(-1).end,title:(cur.chapters&&cur.chapters[j])||mkTitle(lead.t),sum:g.map(x=>x.t).join(' ').slice(0,260).replace(/\s+\S*$/,'')+'…',who:[...new Set(g.map(x=>x.sp))]}}).filter(Boolean);
  chapters.forEach((c,j)=>{if(chapters[j+1])c.end=chapters[j+1].start;else c.end=D});
  const nl_=Math.round(2+r()*10+D/3600*4);
  const laughs=[...Array(nl_)].map(()=>({t:60+r()*(D-120),who:spk[Math.floor(r()*spk.length)],size:1+Math.floor(r()*3)})).sort((a,b)=>a.t-b.t);
  let v=.5;const energy=[...Array(80)].map((_,i)=>{v+= (r()-.5)*.18;v=Math.max(.12,Math.min(.95,v));const t=i/79*D;const bump=laughs.reduce((a,l)=>a+Math.max(0,.25-Math.abs(l.t-t)/D*6)*l.size/2,0);return Math.min(1,v+bump)});
  const bible=pickN(r,BIBLE,Math.floor(r()*(e.th.includes('Bijbel & Jezus')?5:3))).map(b=>({b,t:r()*D})).sort((a,b)=>a.t-b.t);
  const thinkers=[...new Set([...e.sj,...pickN(r,THINKERS,1+Math.floor(r()*4))])].map(n=>({n,t:r()*D,x:1+Math.floor(r()*r()*6)})).sort((a,b)=>b.x-a.x);
  const god=Math.round((e.th.includes('God & geloof')?14:3)+r()*38*D/4500);
  const interrupts=Math.round(2+r()*20);
  const tldr=cur.tldr||sents.slice(0,2).join(' ');
  const kw=new Set(e.kw);const points=cur.points||sents.filter(s=>!/\?/.test(s)&&s.length>40&&s.length<260).map(s=>[s,tok(s).filter(w=>kw.has(w)).length]).sort((a,b)=>b[1]-a[1]).slice(0,4).map(x=>x[0]);
  const hls=[];
  e.q.forEach(q=>{const sg=segs.find(s=>s.t.includes(q.slice(0,25)));hls.push({t:sg?sg.start+sg.dur*.3:r()*D,kind:'Uitspraak',html:`‘${esc(q)}’`,who:sg?sg.sp:guests[0]||paas||spk[0]})});
  const big=[...laughs].sort((a,b)=>b.size-a.size)[0];if(big)hls.push({t:big.t,kind:'Grootste lachsalvo',html:`Gelach aan tafel, ingezet door ${esc(big.who.name)}.`,who:big.who});
  const mono=[...segs].sort((a,b)=>b.dur-a.dur)[0];if(mono)hls.push({t:mono.start,kind:'Langste monoloog',html:`${esc(mono.sp.name)} aan het woord, ${Math.round(mono.dur/60)} minuten zonder onderbreking.`,who:mono.sp});
  const peak=energy.indexOf(Math.max(...energy));hls.push({t:peak/79*D,kind:'Meest geanimeerd',html:'Het moment met de meeste stemverheffing en het snelste tempo.',who:null});
  hls.sort((a,b)=>a.t-b.t);
  const bingo=BINGO.map(b=>({b,hit:r()<.42,t:r()*D}));
  return TX[e.key]={spk,segs,chapters,laughs,energy,bible,thinkers,god,interrupts,tldr,points,hls,bingo,D};
}
function riverHTML(T,{ticks=true}={}){const D=T.D;return `<div class="river" data-river>${T.segs.map(s=>`<i style="left:${(s.start/D*100).toFixed(2)}%;width:${(s.dur/D*100).toFixed(2)}%;background:${s.sp.c}" title="${ts(s.start)} · ${esc(s.sp.name)}"></i>`).join('')}${ticks?T.chapters.slice(1).map(c=>`<b class="ct" style="left:${(c.start/D*100).toFixed(2)}%"></b>`).join(''):''}${T.laughs.map(l=>`<b class="lg" style="left:${(l.t/D*100).toFixed(2)}%;top:${l.size*4}px" title="Gelach ${ts(l.t)}"></b>`).join('')}</div>`}
const tbtn=t=>`<button class="tbtn" type="button" data-seek="${Math.round(t)}">${ts(t)}</button>`;
const spkName=s=>`<b style="color:${s.c}">${esc(s.name)}</b>`;
let TXTAB='ov';
function txBlock(e){
  const desc=`<div class="prose">${e.x.split('\n').map(p=>`<p>${esc(p)}</p>`).join('')}</div>`;
  if(e.f==='Trailer'||e.f==='Spin-off')return desc;
  const T=transcriptFor(e);
  const tabs=[['ov','Overzicht'],['ch','Hoofdstukken'],['tr','Transcript'],['an','Analyse']];
  return `<div class="txwrap"><div class="tabs" role="tablist">${tabs.map(([k,l])=>`<button type="button" role="tab" class="tab ${TXTAB===k?'on':''}" data-tab="${k}" aria-selected="${TXTAB===k}">${l}</button>`).join('')}<span class="demo" title="Tijden, sprekers en cijfers zijn gesimuleerd">Voorbeelddata</span></div>
  <div class="tabp" data-p="ov" ${TXTAB!=='ov'?'hidden':''}>${ovHTML(e,T,desc)}</div>
  <div class="tabp" data-p="ch" ${TXTAB!=='ch'?'hidden':''}>${chHTML(e,T)}</div>
  <div class="tabp" data-p="tr" ${TXTAB!=='tr'?'hidden':''}>${trHTML(e,T)}</div>
  <div class="tabp" data-p="an" ${TXTAB!=='an'?'hidden':''}>${anHTML(e,T)}</div></div>`;
}
function ovHTML(e,T,desc){
  return `<p class="demonote">Met transcripties worden samenvatting, hoofdstukken en analyse uit het gesprek zelf gehaald. Hier staat voorbeelddata: de tekst komt uit de afleveringsomschrijving, sprekers, tijden en cijfers zijn gesimuleerd.</p>
  <h2>In het kort</h2><p class="tldr">${esc(T.tldr)}</p>
  ${T.points.length?`<h2>Kernpunten</h2><ul class="points">${T.points.map(p=>`<li>${esc(p)}</li>`).join('')}</ul>`:''}
  <h2>Wie is wanneer aan het woord</h2>${riverHTML(T)}<div class="spk">${T.spk.map(s=>`<span><i style="background:${s.c}"></i>${esc(s.name)} <span class="muted num">${Math.round(s.share*100)}%</span></span>`).join('')}<span><i style="background:var(--halo);box-shadow:0 0 0 1.5px var(--engraving)"></i>gelach</span></div>
  <h2>Hoogtepunten</h2><ol class="hl">${T.hls.map(h=>`<li>${tbtn(h.t)}<div><span class="label">${esc(h.kind)}${h.who?' · '+esc(h.who.name):''}</span><p>${h.html}</p></div></li>`).join('')}</ol>
  <h2>Omschrijving van de makers</h2>${desc}`;
}
function chHTML(e,T){
  return `<ol class="chapters">${T.chapters.map(c=>`<li data-ch="${c.j}"><div class="when"><button class="tbtn" type="button" data-seek="${Math.round(c.start)}">${ts(c.start)}</button><span>${Math.max(1,Math.round((c.end-c.start)/60))} min</span></div><div><h3>${esc(c.title)}</h3><p>${esc(c.sum)}</p><div class="who">${c.who.map(s=>`<span><i style="display:inline-block;width:8px;height:8px;border-radius:9px;background:${s.c};margin-right:5px"></i>${esc(s.name)}</span>`).join('')}${T.hls.filter(h=>h.t>=c.start&&h.t<c.end).map(h=>`<span>· ${esc(h.kind)} op ${ts(h.t)}</span>`).join('')}</div></div></li>`).join('')}</ol>`;
}
function segsHTML(T,terms){
  let out='',ci=0,li=0;
  T.segs.forEach(s=>{
    while(ci<T.chapters.length&&T.chapters[ci].start<=s.start+1){if(!terms.length)out+=`<div class="chh">${esc(T.chapters[ci].title)}</div>`;ci++}
    const hit=!terms.length||terms.every(t=>norm(s.t).includes(t));
    if(hit)out+=`<div class="seg" data-si="${s.i}">${tbtn(s.start)}<div>${spkName(s.sp)}<p>${hl(s.t,terms)}</p></div></div>`;
    while(li<T.laughs.length&&T.laughs[li].t<s.end){if(!terms.length)out+=`<div class="lgh">[gelach · ${ts(T.laughs[li].t)}]</div>`;li++}
  });
  return out||'<p class="empty">Niets gevonden in dit transcript.</p>';
}
function trHTML(e,T){
  return `<p class="demonote">Voorbeeld: de zinnen hieronder komen uit de omschrijving en zijn over de sprekers verdeeld. Een echt transcript bevat elk gesproken woord.</p>
  <div class="trctrl"><input type="search" id="tr-q" placeholder="Zoek in dit gesprek" aria-label="Zoek in dit transcript"><label class="check"><input type="checkbox" id="tr-follow" checked> Volg de speler</label></div>
  <div class="segs" id="segs">${segsHTML(T,[])}</div>`;
}
function energySVG(T){
  const W=720,h=170,pl=8,pr=8,pt=12,pb=24,iw=W-pl-pr,ih=h-pt-pb,D=T.D;
  const X=t=>pl+iw*t/D,Y=v=>pt+ih-ih*v;const pts=T.energy.map((v,i)=>[X(i/79*D),Y(v)]);
  let s=`<svg class="c anchart" viewBox="0 0 ${W} ${h}" role="img" aria-label="Energie door de aflevering">`;
  T.chapters.forEach(c=>{s+=`<line class="grid" x1="${X(c.start)}" x2="${X(c.start)}" y1="${pt}" y2="${pt+ih}"/>`});
  s+=`<path d="M${pl},${pt+ih} L${pts.map(p=>p.map(n=>n.toFixed(1)).join(',')).join(' L')} L${W-pr},${pt+ih} Z" fill="var(--gold)" fill-opacity=".35"/>`;
  s+=`<polyline class="line" points="${pts.map(p=>p.map(n=>n.toFixed(1)).join(',')).join(' ')}"/>`;
  T.laughs.forEach(l=>{const i=Math.round(l.t/D*79);s+=`<circle cx="${X(l.t).toFixed(1)}" cy="${Y(T.energy[i]).toFixed(1)}" r="${2+l.size}" fill="var(--halo)" stroke="var(--engraving)" stroke-width="1.5"><title>Gelach ${ts(l.t)}</title></circle>`});
  [0,.25,.5,.75,1].forEach(f=>{s+=`<text x="${X(f*D)}" y="${h-6}" text-anchor="${f===0?'start':f===1?'end':'middle'}">${ts(f*D)}</text>`});
  return s+'</svg>';
}
function anHTML(e,T){
  const words=T.spk.reduce((a,s)=>a+s.words,0),wpm=Math.round(words/(T.spk.reduce((a,s)=>a+s.time,0)/60));
  const ticsUsed=TICS.filter(t=>T.spk.some(s=>s.tics[t]>0));
  const bingoRows=[[0,1,2],[3,4,5],[6,7,8],[0,3,6],[1,4,7],[2,5,8],[0,4,8],[2,4,6]];const bingo=bingoRows.some(r=>r.every(i=>T.bingo[i].hit));
  return `<div class="tiles"><div><b>${nl(words)}</b><span>woorden gesproken</span></div><div><b>${wpm}</b><span>woorden per minuut gemiddeld</span></div><div><b>${T.spk[0].questions}</b><span>vragen van David</span></div><div><b>${T.laughs.length}</b><span>keer gelach</span></div><div><b>${T.interrupts}</b><span>keer door elkaar gepraat</span></div><div><b>${T.god}×</b><span>het woord ‘God’</span></div></div>
  <h2>Spreektijd</h2>${hbars(T.spk.map(s=>({l:s.name,v:Math.round(s.share*100),href:'#p-'+slug(s.name)})),{fmt:v=>v+'%',max:100})}
  <h2>Spreektempo</h2><p class="ui muted" style="font-size:13px;margin:-4px 0 10px">Woorden per minuut in deze aflevering.</p>${hbars(T.spk.map(s=>({l:s.name,v:s.wpm})),{cls:'v',max:200})}
  <h2>Verloop van het gesprek</h2><p class="ui muted" style="font-size:13px;margin:-4px 0 0">Energie op basis van tempo en volume; witte stippen zijn lachmomenten, lijnen markeren hoofdstukken.</p>${energySVG(T)}
  <h2>Stopwoordjes</h2><div class="scroll"><table class="tics"><thead><tr><th></th>${T.spk.map(s=>`<th style="color:${s.c}">${esc(s.name.split(' ')[0])}</th>`).join('')}</tr></thead><tbody>${ticsUsed.map(t=>{const mx=Math.max(...T.spk.map(s=>s.tics[t]));return `<tr><td>‘${t}’</td>${T.spk.map(s=>`<td class="${s.tics[t]===mx&&mx>3?'hot':''}">${s.tics[t]||'·'}</td>`).join('')}</tr>`}).join('')}</tbody></table></div>
  <h2>Langste monoloog</h2><div class="mentions">${T.spk.filter(s=>s.longestSeg).map(s=>`<div>${tbtn(s.longestSeg.start)} ${spkName(s)} <span class="muted ui">${Math.max(1,Math.round(s.longest/60))} min aan één stuk</span></div>`).join('')}</div>
  <h2>Woordenschat</h2><p class="ui muted" style="font-size:13px;margin:-4px 0 10px">Aandeel unieke woorden per 1.000 gesproken woorden. Hoger betekent gevarieerder taalgebruik.</p>${hbars(T.spk.map(s=>({l:s.name,v:Math.round(s.ttr*1000)})),{max:500})}
  ${T.bible.length?`<h2>Bijbelverwijzingen</h2><div class="mentions">${T.bible.map(b=>`<div>${tbtn(b.t)} ${esc(b.b)}</div>`).join('')}</div>`:''}
  <h2>Genoemde denkers en figuren</h2><div class="mentions">${T.thinkers.map(x=>`<div>${tbtn(x.t)} ${esc(x.n)} <span class="muted ui">${x.x}× genoemd</span></div>`).join('')}</div>
  <h2>Ongelooflijke bingo</h2><p class="ui muted" style="font-size:13px;margin:-4px 0 10px">Vaste ingrediënten van de show. Een gouden vakje viel in deze aflevering; klik op de tijd om het terug te horen.</p>
  <div class="bingo">${T.bingo.map(b=>`<div class="${b.hit?'hit':''}"><span>${esc(b.b)}</span>${b.hit?tbtn(b.t):''}</div>`).join('')}</div>${bingo?'<p class="bingo-yes">Bingo!</p>':''}`;
}
// ---- demo player ----
let PL=null;
function playerHTML(e,T){return `<div class="player" id="player" role="region" aria-label="Voorbeeldspeler"><div class="wrap pl">
  <button class="pbtn" id="pl-play" type="button" aria-label="Afspelen"><svg viewBox="0 0 24 24" id="pl-ico"><path d="M7 4l13 8-13 8z"/></svg></button>
  <div style="min-width:0"><div class="ptop"><span class="pch" id="pl-ch"></span><span class="pt"><span id="pl-t">0:00</span> / ${ts(T.D)}</span></div>
  <div class="pscrub">${riverHTML(T,{ticks:true})}<b class="phead" id="pl-head" style="left:0"></b></div><div class="pnote">Voorbeeldspeler zonder geluid · springt naar elk moment in het gesprek</div></div>
  <button class="prate" id="pl-rate" type="button" aria-label="Afspeelsnelheid">1×</button></div></div>`}
function mountTx(e){
  if(PL&&PL.raf)cancelAnimationFrame(PL.raf);PL=null;
  if(e.f==='Trailer'||e.f==='Spin-off')return;
  const T=transcriptFor(e);app.classList.add('has-player');app.insertAdjacentHTML('beforeend',playerHTML(e,T));
  PL={e,T,t:0,playing:false,rate:1,last:0,raf:0,seg:-1,ch:-1};
  $('#pl-play').onclick=()=>{PL.playing=!PL.playing;if(PL.playing){if(PL.t>=T.D)PL.t=0;PL.last=performance.now();PL.raf=requestAnimationFrame(tick)}upd()};
  const RATES=[1,2,10,60];$('#pl-rate').onclick=ev=>{PL.rate=RATES[(RATES.indexOf(PL.rate)+1)%RATES.length];ev.currentTarget.textContent=PL.rate+'×'};
  const q=$('#tr-q');if(q)q.oninput=()=>{$('#segs').innerHTML=segsHTML(T,parseTerms(q.value));PL.seg=-1;upd()};
  if(PEND!=null){const t=PEND;PEND=null;setTab('tr');seek(t)}else upd();
}
let PEND=null;
function setTab(k){TXTAB=k;document.querySelectorAll('.tab').forEach(b=>{b.classList.toggle('on',b.dataset.tab===k);b.setAttribute('aria-selected',b.dataset.tab===k)});document.querySelectorAll('.tabp').forEach(p=>p.hidden=p.dataset.p!==k);if(PL){PL.seg=-1;upd()}}
function seek(t){if(!PL)return;PL.t=Math.max(0,Math.min(PL.T.D,t));PL.seg=-1;upd(true)}
function tick(now){if(!PL||!PL.playing)return;PL.t+=(now-PL.last)/1000*PL.rate;PL.last=now;if(PL.t>=PL.T.D){PL.t=PL.T.D;PL.playing=false}upd();if(PL.playing)PL.raf=requestAnimationFrame(tick)}
function upd(jump){
  if(!PL)return;const T=PL.T,t=PL.t;
  const head=$('#pl-head');if(!head)return;head.style.left=(t/T.D*100).toFixed(3)+'%';$('#pl-t').textContent=ts(t);
  $('#pl-ico').innerHTML=PL.playing?'<path d="M6 4h4v16H6zM14 4h4v16h-4z"/>':'<path d="M7 4l13 8-13 8z"/>';$('#pl-play').setAttribute('aria-label',PL.playing?'Pauzeer':'Afspelen');
  const ci=T.chapters.findIndex(c=>t>=c.start&&t<c.end);const sg=T.segs.find(s=>t>=s.start&&t<s.end);
  if(ci!==PL.ch){PL.ch=ci;$('#pl-ch').textContent=ci>=0?`${ci+1}. ${T.chapters[ci].title}`:'';document.querySelectorAll('.chapters li').forEach(li=>li.classList.toggle('cur',+li.dataset.ch===ci))}
  const si=sg?sg.i:-1;if(si!==PL.seg){PL.seg=si;document.querySelectorAll('.seg.on').forEach(x=>x.classList.remove('on'));const el=document.querySelector(`.seg[data-si="${si}"]`);if(el){el.classList.add('on');const f=$('#tr-follow');if(TXTAB==='tr'&&f&&f.checked){const box=$('#segs');box.scrollTo({top:el.offsetTop-box.offsetTop-40,behavior:jump?'auto':'smooth'})}}}
}
document.addEventListener('click',ev=>{
  const s=ev.target.closest('[data-seek]');if(s){seek(+s.dataset.seek);if(PL&&!PL.playing){$('#pl-play').click()}return}
  const tb=ev.target.closest('[data-tab]');if(tb){setTab(tb.dataset.tab);return}
  const rv=ev.target.closest('[data-river]');if(rv&&PL){const b=rv.getBoundingClientRect();seek((ev.clientX-b.left)/b.width*PL.T.D);return}
  const fa=ev.target.closest('[data-seekafter]');if(fa){PEND=+fa.dataset.seekafter}
});
function fragHits(e,terms){if(e.f==='Trailer'||e.f==='Spin-off')return '';const T=transcriptFor(e);const hits=T.segs.filter(s=>terms.every(t=>norm(s.t).includes(t))).slice(0,2);
  return hits.map(s=>{const n=norm(s.t),i=n.indexOf(terms[0]),a=Math.max(0,i-60);return `<a class="frag" href="${e.hash}" data-seekafter="${Math.round(s.start)}"><span class="num">▶ ${ts(s.start)}</span><span><b style="color:${s.sp.c}">${esc(s.sp.name)}</b> ${a?'…':''}${hl(s.t.slice(a,a+170),terms)}${a+170<s.t.length?'…':''}</span></a>`}).join('')}
// ---- aggregates for people and stats ----
function personTx(p){
  const rows=p.eps.filter(e=>e.f!=='Trailer'&&e.f!=='Spin-off').map(e=>{const T=transcriptFor(e);const s=T.spk.find(x=>x.name===p.name);return s?{e,s,T}:null}).filter(Boolean);
  if(!rows.length)return '';
  const time=rows.reduce((a,r)=>a+r.s.time,0),words=rows.reduce((a,r)=>a+r.s.words,0),wpm=Math.round(words/(time/60));
  const share=rows.reduce((a,r)=>a+r.s.share,0)/rows.length;const tics={};rows.forEach(r=>TICS.forEach(t=>tics[t]=(tics[t]||0)+r.s.tics[t]));
  const top=Object.entries(tics).sort((a,b)=>b[1]-a[1])[0];const lo=rows.sort((a,b)=>b.s.longest-a.s.longest)[0];const avg=txAgg().avgWpm;
  const laughs=rows.reduce((a,r)=>a+r.T.laughs.filter(l=>l.who===r.s).length,0);
  return `<div class="panel"><h3 style="display:flex;justify-content:space-between;gap:8px;align-items:center">Uit de transcripties <span class="demo">Voorbeeld</span></h3><dl class="kv">
  <dt>Spreektempo</dt><dd>${wpm} woorden/min <span class="muted">(${wpm>=avg?'+':''}${wpm-avg} t.o.v. gemiddeld)</span></dd>
  <dt>Spreekaandeel</dt><dd>${Math.round(share*100)}% per aflevering</dd>
  <dt>Gesproken</dt><dd>${nl(words)} woorden</dd>
  <dt>Stopwoordje</dt><dd>‘${top[0]}’ <span class="muted">${top[1]}×</span></dd>
  <dt>Langste monoloog</dt><dd><a href="${lo.e.hash}" data-seekafter="${Math.round(lo.s.longestSeg.start)}">${Math.max(1,Math.round(lo.s.longest/60))} min in #${lo.e.n}</a></dd>
  <dt>Zet het gelach in</dt><dd>${laughs}×</dd></dl></div>`;
}
let AGG=null;
function txAgg(){
  if(AGG)return AGG;const P2={},share={},laughYear={},bib={},thk={},tic={};
  REG.forEach(e=>{const T=transcriptFor(e);
    T.spk.forEach(s=>{const a=P2[s.name]=P2[s.name]||{time:0,words:0,n:0};a.time+=s.time;a.words+=s.words;a.n++;TICS.forEach(t=>{const x=tic[t]=tic[t]||{};x[s.name]=(x[s.name]||0)+s.tics[t]})});
    const y=share[e.y]=share[e.y]||{d:0,p:0,n:0};y.d+=T.spk[0].share;y.p+=(T.spk.find(s=>s.role==='Vaste gast')||{share:0}).share;y.n++;
    const ly=laughYear[e.y]=laughYear[e.y]||{l:0,h:0};ly.l+=T.laughs.length;ly.h+=e.s/3600;
    T.bible.forEach(b=>{const bk=b.b.replace(/\s+\d+$/,'');bib[bk]=(bib[bk]||0)+1});T.thinkers.forEach(x=>thk[x.n]=(thk[x.n]||0)+x.x)});
  const tw=Object.values(P2).reduce((a,x)=>a+x.words,0),tt=Object.values(P2).reduce((a,x)=>a+x.time,0);
  return AGG={P2,share,laughYear,bib,thk,tic,avgWpm:Math.round(tw/(tt/60))};
}
function statsTx(){
  const A=txAgg();const speed=Object.entries(A.P2).filter(([n,x])=>x.n>=3).map(([n,x])=>({l:n,v:Math.round(x.words/(x.time/60)),href:'#p-'+slug(n)})).sort((a,b)=>b.v-a.v);
  const ticRows=TICS.map(t=>{const x=A.tic[t];const tot=Object.values(x).reduce((a,b)=>a+b,0);const [who]=Object.entries(x).sort((a,b)=>b[1]-a[1])[0];return {l:`‘${t}’`,v:tot,who}}).sort((a,b)=>b.v-a.v);
  return `<div class="chart wide"><div class="sechead" style="margin:6px 0 0"><h2>Uit de transcripties</h2><span class="demo">Voorbeelddata</span></div><p class="demonote" style="margin:10px 0 0">Zodra transcripties met sprekerherkenning beschikbaar zijn, worden deze grafieken uit het gesproken woord berekend. Nu zijn de cijfers gesimuleerd.</p></div>
  <div class="chart"><h3>Snelste spreker</h3><p class="note">Gemiddeld aantal woorden per minuut, voor wie minstens drie keer aanschoof. Gemiddelde aan tafel: ${A.avgWpm}.</p>${hbars([...speed.slice(0,7),...speed.slice(-3)],{max:200})}<p class="note" style="margin-top:6px">De onderste drie zijn de rustigste sprekers.</p></div>
  <div class="chart"><h3>Wie praat er?</h3><p class="note">Gemiddeld spreekaandeel per aflevering, per jaar.</p>${lines([{name:'David Boogerd',v:YEARS.map(y=>A.share[y]?Math.round(A.share[y].d/A.share[y].n*100):0)},{name:'Stefan Paas',v:YEARS.map(y=>A.share[y]?Math.round(A.share[y].p/A.share[y].n*100):0)},{name:'Gasten',v:YEARS.map(y=>A.share[y]?Math.round(100-(A.share[y].d+A.share[y].p)/A.share[y].n*100):0)}],YEARS.map(String),{h:260,fmt:v=>v+'%'})}</div>
  <div class="chart"><h3>Gelach per uur</h3><p class="note">Hoe vaak er gemiddeld per uur gesprek gelachen wordt.</p>${vbars(YEARS.map(y=>({l:String(y),v:A.laughYear[y]?+(A.laughYear[y].l/A.laughYear[y].h).toFixed(1):0})),{fmt:v=>v.toLocaleString('nl-NL',{maximumFractionDigits:1})})}</div>
  <div class="chart"><h3>Stopwoordjes-hitlijst</h3><p class="note">Totaal over alle afleveringen, met wie het woordje het vaakst gebruikt.</p>${hbars(ticRows.map(r=>({l:`${r.l} · ${r.who.split(' ')[0]}`,v:r.v})),{cls:'v'})}</div>
  <div class="chart"><h3>Meest aangehaalde Bijbelboeken</h3><p class="note">Aantal afleveringen met een verwijzing.</p>${hbars(Object.entries(A.bib).sort((a,b)=>b[1]-a[1]).slice(0,10).map(([l,v])=>({l,v})))}</div>
  <div class="chart"><h3>Meest genoemde denkers</h3><p class="note">Aantal keer dat de naam valt in alle gesprekken.</p>${hbars(Object.entries(A.thk).sort((a,b)=>b[1]-a[1]).slice(0,10).map(([l,v])=>({l,v})),{cls:'v'})}</div>`;
}
// ---- quiz: real quotes from descriptions ----
const QZ={score:0,n:0,cur:null,used:new Set()};
function viewQuiz(){
  const pool=REG.filter(e=>e.g.length===1&&e.q.length&&!QZ.used.has(e.key));
  if(!pool.length)QZ.used.clear();
  const src=pool.length?pool:REG.filter(e=>e.g.length===1&&e.q.length);
  const e=src[Math.floor(Math.random()*src.length)];const q=e.q[Math.floor(Math.random()*e.q.length)];
  const others=GUESTS.filter(p=>p.name!==e.g[0]&&p.eps.length>=1);const opts=[e.g[0],...pickN(Math.random,others.map(p=>p.name),3)].sort(()=>Math.random()-.5);
  QZ.cur={e,q};
  app.innerHTML=`<div class="quiz"><h1>Wie zei het?</h1><p class="prose muted" style="margin:8px 0 6px">Een echte uitspraak uit de afleveringsomschrijvingen. In de aflevering met welke gast viel deze zin?</p>
  <div class="qscore"><span>Score ${QZ.score} / ${QZ.n}</span></div>
  <blockquote class="q">‘${esc(q)}’</blockquote>
  <div class="qopts">${opts.map(o=>`<button class="qopt" type="button" data-ans="${esc(o)}">${esc(o)}</button>`).join('')}</div>
  <div id="qres" style="margin-top:22px"></div></div>`;
  app.querySelectorAll('.qopt').forEach(b=>b.onclick=()=>{
    const ok=b.dataset.ans===e.g[0];QZ.n++;if(ok)QZ.score++;QZ.used.add(e.key);
    app.querySelectorAll('.qopt').forEach(x=>{x.disabled=true;if(x.dataset.ans===e.g[0])x.classList.add('ok');else if(x===b)x.classList.add('bad')});
    $('#qres').innerHTML=`<p style="font-size:19px;margin:0 0 6px"><b>${ok?'Goed!':'Helaas.'}</b> Het komt uit <a href="${e.hash}">#${e.n} ${esc(e.t)}</a>.</p><div class="actions"><button class="btn solid" type="button" id="qnext">Volgende citaat</button><a class="btn" href="#p-${slug(e.g[0])}">Meer over ${esc(e.g[0])}</a></div>`;
    $('#qnext').onclick=viewQuiz;
  });
}
