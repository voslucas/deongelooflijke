
// ---------- mentions: persons, philosophers, books, places (VOORBEELDDATA) ----------
const ENT={
  persoon:['Maarten Luther','Johannes Calvijn','Dietrich Bonhoeffer','C.S. Lewis','Fjodor Dostojevski','Tom Holland','Abraham Kuyper','Paus Franciscus','Paus Leo XIV','Donald Trump','Vladimir Poetin','Geert Wilders','Martin Luther King','Etty Hillesum','Henri Nouwen','Jordan Peterson','Elon Musk','Willem van Oranje','Desiderius Erasmus','Joe Biden'],
  filosoof:['Augustinus','Thomas van Aquino','Friedrich Nietzsche','Søren Kierkegaard','Baruch Spinoza','Blaise Pascal','Simone Weil','Hannah Arendt','René Girard','Charles Taylor','Plato','Aristoteles','Immanuel Kant','Karl Marx','Emmanuel Levinas','Ludwig Wittgenstein','Jürgen Habermas'],
  boek:['Belijdenissen','Dominion','A Secular Age','De gebroeders Karamazov','Navolging van Christus','Het verstoorde leven','Navolging','Mere Christianity','Also sprach Zarathustra','De Koran','Pensées','Lof der Zotheid','Ethica','De mythe van Sisyphus'],
  plaats:['Jeruzalem','Rome','Amsterdam','Iran','Rusland','Oekraïne','Gaza','Israël','Washington','Brussel','Den Haag','Urk','Staphorst','Athene','Wittenberg','Auschwitz','Taizé','Vaticaanstad','Moskou','Bethlehem']
};
const CATS=[['persoon','Personen','persoon'],['filosoof','Filosofen','filosoof'],['boek','Boeken','boek'],['plaats','Plaatsen','plaats']];
const CATL=Object.fromEntries(CATS.map(c=>[c[0],c[1]])),CAT1=Object.fromEntries(CATS.map(c=>[c[0],c[2]]));
const ENTW={},ENTRX={};
Object.entries(ENT).forEach(([c,l])=>{const r=rng('w'+c);pickN(r,l,l.length).forEach((n,i)=>ENTW[n]=1/Math.pow(i+1,.85));
  l.forEach(n=>{const al=[norm(n.replace(/^Paus /,''))];const last=n.split(' ').at(-1);if((c==='persoon'||c==='filosoof')&&last.length>=5&&!/^(king|oranje|franciscus)$/i.test(last))al.push(norm(last));ENTRX[n]=al.map(wre)})});
function wpick(r,list,n){const a=[...list],out=[];while(out.length<n&&a.length){const tot=a.reduce((s,x)=>s+ENTW[x],0);let v=r()*tot,i=0;for(;i<a.length-1;i++){v-=ENTW[a[i]];if(v<=0)break}out.push(a.splice(i,1)[0])}return out}
const NUMC={persoon:[1,4],filosoof:[0,3],boek:[0,2],plaats:[1,3]};
function mentionsFor(e,T,r){
  const txt=norm(e.t+' '+e.x),out=[];
  for(const [c,l] of Object.entries(ENT)){
    const forced=l.filter(n=>ENTRX[n].some(rx=>rx.test(txt)));
    const k=NUMC[c][0]+Math.floor(r()*(NUMC[c][1]-NUMC[c][0]+1));
    const chosen=[...forced,...wpick(r,l.filter(n=>!forced.includes(n)),Math.max(0,k-forced.length))];
    chosen.forEach(n=>{const real=forced.includes(n),x=real?3+Math.floor(r()*6):1+Math.floor(r()*r()*5);
      const hits=[...Array(x)].map(()=>({t:30+r()*(T.D-60),sp:T.spk[Math.floor(r()*T.spk.length)]})).sort((a,b)=>a.t-b.t);
      out.push({n,c,x,hits,real})});
  }
  return out.sort((a,b)=>b.x-a.x);
}
let MAGG=null;
function mentionAgg(){
  if(MAGG)return MAGG;const M={};
  REG.forEach(e=>{const T=transcriptFor(e);T.ment.forEach(m=>{const a=M[m.n]=M[m.n]||{n:m.n,c:m.c,k:slug(m.n),x:0,eps:[],sp:{},yr:{}};a.x+=m.x;a.eps.push({e,m});a.yr[e.y]=(a.yr[e.y]||0)+m.x;m.hits.forEach(h=>a.sp[h.sp.name]=(a.sp[h.sp.name]||0)+1)})});
  Object.values(M).forEach(a=>{a.eps.sort((p,q)=>p.e.d<q.e.d?-1:1);a.top=Object.entries(a.sp).sort((p,q)=>q[1]-p[1])[0]});
  MAGG={M,list:Object.values(M).filter(a=>a.eps.length>1||a.x>1),byK:Object.fromEntries(Object.values(M).map(a=>[a.k,a]))};return MAGG;
}
function spark(a){const max=Math.max(...YEARS.map(y=>a.yr[y]||0))||1,w=8,g=3,h=26;return `<svg class="c spark" viewBox="0 0 ${YEARS.length*(w+g)} ${h}" width="${YEARS.length*(w+g)}" height="${h}" aria-hidden="true">${YEARS.map((y,i)=>{const v=a.yr[y]||0,bh=Math.max(v?2:1,(h-2)*v/max);return `<rect x="${i*(w+g)}" y="${h-bh}" width="${w}" height="${bh}" rx="1.5" class="${v?'bar':'grid'}" ${v?'':'style="fill:var(--rule)"'}><title>${y}: ${v}×</title></rect>`}).join('')}</svg>`}
const MS={cat:'',q:'',sort:'x',min:2};
function viewMentions(){
  const A=mentionAgg();
  app.innerHTML=`<div class="sechead" style="border:0;margin:0"><h1>Genoemd</h1><span class="demo">Voorbeelddata</span></div>
  <p class="prose muted" style="margin:8px 0 6px">Personen, filosofen, boeken en plaatsen die in de gesprekken vallen, en waarnaar vaker dan één keer wordt verwezen. Klik op een naam voor alle momenten waarop die genoemd wordt.</p>
  <p class="demonote">Met transcripties worden deze namen automatisch herkend in het gesproken woord. Nu zijn de vermeldingen gesimuleerd; namen die ook in de afleveringsomschrijving staan, tellen zwaarder mee.</p>
  <div id="mtop"></div>
  <div class="ctrl" style="margin-top:26px"><div class="chips" style="margin:0" id="mcat"></div></div>
  <div class="ctrl"><input id="mq" type="search" placeholder="Zoek een naam, boek of plaats" aria-label="Zoek in genoemde namen" value="${esc(MS.q)}" style="flex:1 1 220px">
  <label>In minstens <select id="mmin">${[1,2,3,5,10].map(n=>`<option value="${n}" ${MS.min===n?'selected':''}>${n} ${n===1?'aflevering':'afleveringen'}</option>`).join('')}</select></label>
  <label>Sorteer <select id="msort"><option value="x">Meest genoemd</option><option value="e">In meeste afleveringen</option><option value="r">Recent genoemd</option><option value="a">A–Z</option></select></label></div>
  <div id="mlist"></div>`;
  $('#msort').value=MS.sort;
  const cnt=c=>A.list.filter(a=>(!c||a.c===c)&&a.eps.length>=MS.min).length;
  const drawCats=()=>{$('#mcat').innerHTML=[['','Alles'],...CATS].map(([k,l])=>`<button type="button" class="chip ${MS.cat===k?'on':''}" data-mcat="${k}">${l} <span>${cnt(k)}</span></button>`).join('');
    $('#mcat').querySelectorAll('[data-mcat]').forEach(b=>b.onclick=()=>{MS.cat=b.dataset.mcat;drawCats();drawList()})};
  const S={x:(a,b)=>b.x-a.x,e:(a,b)=>b.eps.length-a.eps.length||b.x-a.x,r:(a,b)=>a.eps.at(-1).e.d<b.eps.at(-1).e.d?1:-1,a:(a,b)=>a.n.localeCompare(b.n,'nl')};
  const drawList=()=>{const q=norm(MS.q);const rows=A.list.filter(a=>(!MS.cat||a.c===MS.cat)&&a.eps.length>=MS.min&&(!q||norm(a.n).includes(q))).sort(S[MS.sort]);
    $('#mtop').innerHTML=(!MS.cat&&!q)?`<div class="mtop">${CATS.map(([c,l])=>{const t=A.list.filter(a=>a.c===c).sort(S.x).slice(0,5);return `<div><h3>${l}</h3><ol>${t.map(a=>`<li><a href="#m-${a.k}">${esc(a.n)}</a><span class="num muted">${a.x}×</span></li>`).join('')}</ol></div>`}).join('')}</div>`:'';
    $('#mlist').innerHTML=rows.length?`<div class="scroll"><table class="mtab"><thead><tr><th>Naam</th><th>Soort</th><th class="r">Keer genoemd</th><th class="r">Afleveringen</th><th>${YEARS[0]}–${YEARS.at(-1)}</th><th>Vaakst genoemd door</th></tr></thead><tbody>${rows.map(a=>`<tr><td><a href="#m-${a.k}"><b>${esc(a.n)}</b></a></td><td><span class="mcat mcat-${a.c}">${CAT1[a.c]}</span></td><td class="r num">${a.x}</td><td class="r num">${a.eps.length}</td><td>${spark(a)}</td><td class="muted">${esc(a.top[0])}</td></tr>`).join('')}</tbody></table></div>`:'<p class="empty">Geen namen gevonden. Probeer een ander woord of verlaag het minimum.</p>'};
  $('#mq').oninput=ev=>{MS.q=ev.target.value;drawList()};$('#msort').onchange=ev=>{MS.sort=ev.target.value;drawList()};$('#mmin').onchange=ev=>{MS.min=+ev.target.value;drawCats();drawList()};
  drawCats();drawList();
}
function viewMention(a){
  if(!a)return notFound();const A=mentionAgg();
  const co={};a.eps.forEach(({e})=>transcriptFor(e).ment.forEach(m=>{if(m.n!==a.n)co[m.n]=(co[m.n]||0)+1}));
  const coRows=Object.entries(co).filter(([n])=>A.M[n]).sort((p,q)=>q[1]-p[1]).slice(0,12);
  const eps=[...a.eps].reverse();
  app.innerHTML=`<div class="crumb"><a href="#genoemd">Genoemd</a> / ${esc(a.n)}</div>
  <div class="detail"><div style="min-width:0"><div class="epno">${CAT1[a.c]}</div><div class="sechead" style="border:0;margin:4px 0 0;padding:0"><h1>${esc(a.n)}</h1><span class="demo">Voorbeelddata</span></div>
  <div class="facts"><div><b>${a.x}</b><span>keer genoemd</span></div><div><b>${a.eps.length}</b><span>afleveringen</span></div><div><b>${fdate(a.eps[0].e.d).replace(/^\d+ /,'')}</b><span>voor het eerst</span></div><div><b>${fdate(a.eps.at(-1).e.d).replace(/^\d+ /,'')}</b><span>voor het laatst</span></div></div>
  <section style="margin-top:28px"><h2>Per jaar</h2><p class="ui muted" style="font-size:13px;margin:4px 0 8px">Aantal keer dat de naam valt.</p>${vbars(YEARS.map(y=>({l:String(y),v:a.yr[y]||0})),{h:170})}</section>
  <section style="margin-top:28px"><div class="sechead"><h2>Waar het valt</h2><span class="label">nieuwste eerst</span></div>
  ${eps.map(({e,m})=>`<article class="ep"><div class="no">${e.n!=null?'#'+e.n:'—'}</div><div style="min-width:0"><h3><a href="${e.hash}">${esc(e.t)}</a></h3><div class="meta">${fdate(e.d)} · ${m.x}× genoemd${m.real?' · staat ook in de omschrijving':''}</div>
  <div class="mhits">${m.hits.map(h=>`<a class="frag" href="${e.hash}" data-seekafter="${Math.round(h.t)}"><span class="num">▶ ${ts(h.t)}</span><span><b style="color:${h.sp.c}">${esc(h.sp.name)}</b></span></a>`).join('')}</div></div><div class="dur">${fdur(e.s)}</div></article>`).join('')}</section></div>
  <aside class="side"><div class="panel"><h3>Wie noemt het</h3>${hbars(Object.entries(a.sp).sort((p,q)=>q[1]-p[1]).slice(0,8).map(([l,v])=>({l,v,href:'#p-'+slug(l)})))}</div>
  ${coRows.length?`<div class="panel"><h3>Vaak in hetzelfde gesprek</h3><div class="chips" style="margin:0">${coRows.map(([n,v])=>`<a class="chip" href="#m-${slug(n)}">${esc(n)} <span class="muted">${v}</span></a>`).join('')}</div></div>`:''}
  <div class="panel"><h3>Meer ${CATL[a.c].toLowerCase()}</h3><div class="chips" style="margin:0">${A.list.filter(x=>x.c===a.c&&x!==a).sort((p,q)=>q.x-p.x).slice(0,10).map(x=>`<a class="chip" href="#m-${x.k}">${esc(x.n)}</a>`).join('')}</div></div></aside></div>`;
}
