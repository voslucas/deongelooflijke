/* app.js — client-side interactivity for the static site */
(function () {
  'use strict';

  var page = (document.querySelector('main') || {}).dataset.page || '';

  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function ts(s) {
    s = Math.round(s);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    return (h ? h + ':' + String(m).padStart(2, '0') : m)
      + ':' + String(sec).padStart(2, '0');
  }

  // ── Book cover fallback (mirrors SPA bkCover) ───────────────────────────────
  window.bkCover = function (el) {
    var fb = el.dataset.fb || '';
    el.dataset.fb = '';
    if (fb) {
      el.onerror = function () { bkCover(el); };
      el.onload = null;
      el.src = fb;
    } else {
      el.style.display = 'none';
      var icon = el.nextElementSibling;
      if (icon) icon.style.display = 'flex';
    }
  };

  // ── Shared: Bible verse popup ───────────────────────────────────────────────
  var _bvdata = null;
  function initBiblePopup() {
    document.addEventListener('click', function (e) {
      var btn = e.target.closest('[data-bvref]');
      if (!btn) return;
      e.preventDefault();
      // Inline verse data takes priority (no fetch needed)
      if (btn.dataset.vv) {
        showBvPopup(btn, btn.dataset.bvref, JSON.parse(btn.dataset.vv));
        return;
      }
      var ref = btn.dataset.bvref;
      if (!_bvdata) {
        fetch('/data/bvdata.json').then(function (r) { return r.json(); })
          .then(function (d) { _bvdata = d; showBvPopup(btn, ref, null); })
          .catch(function () { showBvPopup(btn, ref, []); });
      } else {
        showBvPopup(btn, ref, null);
      }
    });
  }

  function showBvPopup(anchor, ref, inlineVerses) {
    var old = document.getElementById('bv-popup');
    if (old) old.remove();
    var parts = ref.split('.');
    var key = parts[0] + '.' + parts[1] + '.' + parts[2];
    var verses = inlineVerses || (_bvdata && _bvdata[key]) || [];
    var popup = document.createElement('div');
    popup.id = 'bv-popup';
    popup.style.cssText = 'position:fixed;z-index:9999;max-width:380px;background:var(--parchment-2);'
      + 'border:1px solid var(--rule);border-radius:10px;padding:14px 16px;box-shadow:0 4px 24px rgba(0,0,0,.15);';
    var rect = anchor.getBoundingClientRect();
    var top = rect.bottom + 8;
    if (top + 160 > window.innerHeight) top = rect.top - 160;
    popup.style.top = Math.max(8, top) + 'px';
    popup.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 400)) + 'px';
    var vhtml = verses.map(function (v, i) {
      return '<span style="font-size:12px;color:var(--gold-deep);margin-right:4px">'
        + (parseInt(parts[2], 10) + i) + '</span>' + esc(v);
    }).join(' ');
    popup.innerHTML = '<p style="margin:0 0 6px;font-size:13px;font-weight:600;'
      + 'color:var(--ink-muted)">' + esc(anchor.textContent) + '</p>'
      + '<p style="margin:0;font-family:Spectral,Georgia,serif;font-size:15px;'
      + 'line-height:1.6;font-style:italic">' + (vhtml || 'Voor deze verwijzing is geen tekst beschikbaar.') + '</p>'
      + '<a class="bv-link" href="https://nbv21.nl/bijbel/NBV21/'
      + encodeURIComponent(parts[0] + '.' + parts[1]) + '/" target="_blank" rel="noopener"'
      + ' style="display:inline-block;margin-top:10px;font-family:var(--ui);font-size:12px;'
      + 'color:var(--violet);text-decoration:none;padding:4px 10px;border:1px solid var(--violet);'
      + 'border-radius:999px">Lees in NBV21</a>';
    document.body.appendChild(popup);
    setTimeout(function () {
      document.addEventListener('click', function rm(ev) {
        if (!popup.contains(ev.target)) { popup.remove(); document.removeEventListener('click', rm); }
      });
    }, 100);
  }

  // ── Home: random episode navigation ────────────────────────────────────────
  function initRandom() {
    var btn = document.getElementById('btn-random');
    if (!btn) return;
    var keysEl = document.getElementById('ep-keys');
    var keys = keysEl ? JSON.parse(keysEl.textContent) : [];
    btn.addEventListener('click', function () {
      if (!keys.length) return;
      var key = keys[Math.floor(Math.random() * keys.length)];
      location.href = '/aflevering/' + key + '/';
    });
  }

  // ── Episode list: filter + count ───────────────────────────────────────────
  function initEpisodeFilter() {
    var list = document.getElementById('ep-list');
    var qEl = document.getElementById('ep-q');
    var yearEl = document.getElementById('ep-year');
    var themeEl = document.getElementById('ep-theme');
    var fmtEl = document.getElementById('ep-fmt');
    var paasEl = document.getElementById('ep-paas');
    var resetBtn = document.getElementById('ep-reset');
    var countEl = document.getElementById('ep-count');
    if (!list) return;
    var items = Array.from(list.querySelectorAll('article.ep'));

    function filter() {
      var q = qEl ? qEl.value.trim().toLowerCase() : '';
      var year = yearEl ? yearEl.value : '';
      var theme = themeEl ? themeEl.value : '';
      var fmt = fmtEl ? fmtEl.value : '';
      var paas = paasEl ? paasEl.checked : false;
      var n = 0;
      items.forEach(function (el) {
        var ds = el.dataset;
        var show = true;
        if (year && ds.year !== year) show = false;
        if (theme && !(ds.themes || '').split('|').includes(theme)) show = false;
        if (fmt && ds.fmt !== fmt) show = false;
        if (paas && ds.paas !== '1') show = false;
        if (q) {
          var haystack = (ds.search || el.textContent).toLowerCase();
          if (!haystack.includes(q)) show = false;
        }
        el.classList.toggle('hidden', !show);
        if (show) n++;
      });
      if (countEl) countEl.textContent = n + ' afleveringen';
    }

    if (qEl) qEl.addEventListener('input', filter);
    if (yearEl) yearEl.addEventListener('change', filter);
    if (themeEl) themeEl.addEventListener('change', filter);
    if (fmtEl) fmtEl.addEventListener('change', filter);
    if (paasEl) paasEl.addEventListener('change', filter);
    if (resetBtn) resetBtn.addEventListener('click', function () {
      if (qEl) qEl.value = '';
      if (yearEl) yearEl.value = '';
      if (themeEl) themeEl.value = '';
      if (fmtEl) fmtEl.value = '';
      if (paasEl) paasEl.checked = false;
      filter();
    });
  }

  // ── Guest list: filter + sort ───────────────────────────────────────────────
  function initGuestFilter() {
    var qEl = document.getElementById('guest-q');
    var sortEl = document.getElementById('guest-sort');
    var list = document.getElementById('plist');
    if (!list) return;
    var items = Array.from(list.querySelectorAll('a.person'));

    function apply() {
      var q = qEl ? qEl.value.trim().toLowerCase() : '';
      items.forEach(function (el) {
        var name = (el.dataset.name || el.textContent).toLowerCase();
        el.classList.toggle('hidden', q.length > 0 && !name.includes(q));
      });
      if (sortEl) {
        var by = sortEl.value;
        items.sort(function (a, b) {
          if (by === 'alpha') {
            return (a.dataset.name || '').localeCompare(b.dataset.name || '', 'nl');
          }
          return (parseInt(b.dataset.count, 10) || 0) - (parseInt(a.dataset.count, 10) || 0);
        });
        items.forEach(function (el) { list.appendChild(el); });
      }
    }
    if (qEl) qEl.addEventListener('input', apply);
    if (sortEl) sortEl.addEventListener('change', apply);
  }

  // ── Persons list: filter + year chips ──────────────────────────────────────
  function initPersonsFilter() {
    var qEl = document.getElementById('pm-q');
    var listEl = document.getElementById('pmlist');
    if (!listEl) return;
    var allItems = Array.from(listEl.querySelectorAll('[data-name]'));

    if (qEl) {
      qEl.addEventListener('input', function () {
        var q = qEl.value.trim().toLowerCase();
        allItems.forEach(function (el) {
          el.classList.toggle('hidden', q.length > 0 && !(el.dataset.name || '').includes(q));
        });
      });
    }
  }

  // ── Books list: filter ──────────────────────────────────────────────────────
  function initBooksFilter() {
    var qEl = document.getElementById('bk-q');
    if (!qEl) return;
    var items = Array.from(document.querySelectorAll('[data-title]'));
    qEl.addEventListener('input', function () {
      var q = qEl.value.trim().toLowerCase();
      items.forEach(function (el) {
        el.classList.toggle('hidden', q.length > 0 && !(el.dataset.title || '').includes(q));
      });
    });
  }

  // ── Episode detail: tabs ────────────────────────────────────────────────────
  function initTabs() {
    var tablist = document.querySelector('.tabs');
    if (!tablist) return;
    var tabs = Array.from(tablist.querySelectorAll('.tab'));
    var panels = Array.from(document.querySelectorAll('.tabp'));

    tabs.forEach(function (tab) {
      tab.addEventListener('click', function () {
        var target = tab.dataset.tab;
        tabs.forEach(function (t) {
          t.classList.toggle('on', t === tab);
          t.setAttribute('aria-selected', t === tab);
        });
        panels.forEach(function (p) {
          p.hidden = p.dataset.p !== target;
        });
      });
    });
  }

  // ── Episode detail: timestamp seek ─────────────────────────────────────────
  document.addEventListener('click', function (e) {
    var btn = e.target.closest('[data-seek]');
    if (!btn) return;
    var t = parseInt(btn.dataset.seek, 10);
    if (window._PL && window._PL.audio) {
      window._PL.audio.currentTime = t;
      if (window._PL.audio.paused) window._PL.audio.play().catch(function () {});
    }
  });

  // ── Speaker colours ─────────────────────────────────────────────────────────
  var SPEAKER_COLORS = {
    'David Boogerd': 'var(--ink)',
    'Stefan Paas': 'var(--gold-deep)'
  };
  var GUEST_COLORS = ['var(--violet)', 'var(--teal)', 'var(--rose)'];
  var _gci = 0;
  var _colorMap = {};

  function colorFor(sp) {
    if (SPEAKER_COLORS[sp]) return SPEAKER_COLORS[sp];
    if (!_colorMap[sp]) _colorMap[sp] = GUEST_COLORS[_gci++ % GUEST_COLORS.length];
    return _colorMap[sp];
  }

  // Match the SPA tok() rules: content words, lowercase, without punctuation.
  // Keep this list in sync with index.template.html; tests/test_vocabulary.py checks parity.
  var VOCABULARY_STOP = new Set(`aan aangezien achter af al alle allemaal alleen alles als altijd ander andere anders behalve beide ben bent beter bij binnen boven bovendien daar daarbij daarin daarna daarom daarover dan dat de deze die dit doch doen door dus echter een eens eerst eerste elk elke en enige enkele enz er erg ergens even ga gaan gaat geen gehad geweest gewoon haar had heb hebben heeft hem het hier hij hoe hoewel hun ik in is ja je jij jou jouw juist kan kon konden kun kunnen maar me meer meeste men met mij mijn misschien moet moeten na naar nadat net niet niets nog nooit nu of om omdat onder ons onze ook op over pas per plaats reeds rond samen sinds sommige steeds te tegen ten ter tijdens toch toe toen tot tussen u uit uw van vanaf veel verder via vol voor vooral vrij waar waarom wanneer want waren was wat we wel welk welke werd werden wie wij wil willen word worden wordt zal ze zelf zich zichzelf zij zijn zo zoals zodat zonder zou zouden zulke bijvoorbeeld eigenlijk echt heel weer gaat komt komen kwam maakt maken laat laten staat staan zegt zeggen zien ziet waarin waarmee waardoor iets iemand jaar jaren keer onze deze dezen hele zeer best goed groot grote kleine klein nieuwe nieuw oude lang lange veel vele weinig andere eigen manier vraag vragen vraagt waarbij hierover welke zowel zult wellicht vaak soms tweede twee drie vier vijf zes zeven acht negen tien honderd duizend daarnaast zelfs bijna helemaal tegelijkertijd terwijl totdat volgens tijdens binnenkort inmiddels ondanks verschillende eerder later vandaag gisteren morgen uiteraard natuurlijk volgens ervan erover ermee erin hierin waarover hebt had heeft zitten zit kunnen krijgen krijgt gaan ging gingen gaat moet mogen mag spreekt spreken sprak praat praten gesprek gesprekken aflevering afleveringen podcast ongelooflijke david boogerd stefan paas vaste gast gasten theoloog hoogleraar universiteit spreekt bespreken bespreekt bespreekt vertelt vertellen waarover samen luister luisteren deel nieuwste vorige volgende waarom hoe wat wie welke anno ging zien doet deed gedaan leven mensen mens dingen ding wereld vindt vinden vond denk denkt dacht nederland nederlandse amsterdam utrecht theologische vrije`.split(/\s+/));
  function vocabularyTokens(text) {
    return (text.toLowerCase().match(/[a-zà-öø-ÿ]+(?:-[a-zà-öø-ÿ]+)*/g) || [])
      .filter(function (word) { return word.length > 3 && !VOCABULARY_STOP.has(word); });
  }

  // ── Transcript: parse raw data ──────────────────────────────────────────────
  function parseTranscript(tr, dur) {
    var rawSegs = tr.segments || tr.utterances || [];
    // Build ID→name map from speakers array
    var idToName = {};
    (tr.speakers || []).forEach(function (s) { if (s.id && s.name) idToName[s.id] = s.name; });
    var parsed = [];
    rawSegs.forEach(function (seg) {
      var rawSpId = seg.speaker || seg.name || '';
      var spName = idToName[rawSpId] || rawSpId;
      var text = (seg.text || seg.words || '').trim();
      var start = seg.start !== undefined ? seg.start : (seg.start_time || 0);
      var end = seg.end !== undefined ? seg.end : (seg.end_time || start);
      if (!text) return;
      parsed.push({ i: parsed.length, sp: spName, t: text, start: start, end: end,
                    dur: Math.max(0, end - start) });
    });
    // Build speaker summary (colorFor() assigns colours in first-seen order)
    var spkMap = {};
    parsed.forEach(function (s) {
      if (!spkMap[s.sp]) spkMap[s.sp] = { name: s.sp, c: colorFor(s.sp), time: 0 };
      spkMap[s.sp].time += s.dur;
    });
    var totalTime = parsed.reduce(function (a, s) { return a + s.dur; }, 0) || dur || 1;
    var spk = Object.values(spkMap).sort(function (a, b) { return b.time - a.time; });
    spk.forEach(function (s) { s.share = s.time / totalTime; });

    // Per-speaker tics, ttr, wpm
    var TICS_LIST = ['eigenlijk', 'zeg maar', 'nou', 'weet je', 'in die zin', 'als het ware', 'precies', 'interessant'];
    spk.forEach(function (s) {
      var mine = parsed.filter(function (seg) { return seg.sp === s.name; });
      var allWords = mine.map(function (seg) { return seg.t.toLowerCase().split(/\s+/); }).reduce(function (a, b) { return a.concat(b); }, []);
      s.wpm = s.time > 0 ? Math.round(allWords.length / (s.time / 60)) : 0;
      var contentWords = mine.map(function (seg) { return vocabularyTokens(seg.t); })
        .reduce(function (a, b) { return a.concat(b); }, []);
      s.ttr = contentWords.length > 0
        ? Number((new Set(contentWords).size / contentWords.length).toFixed(3)) : 0;
      s.tics = {};
      var fullText = mine.map(function (seg) { return seg.t.toLowerCase(); }).join(' ');
      TICS_LIST.forEach(function (tic) {
        var re = new RegExp('\\b' + tic.replace(/\s+/g, '\\s+') + '\\b', 'g');
        s.tics[tic] = (fullText.match(re) || []).length;
      });
    });

    // Energy: 80-bucket WPM, normalised 0–1
    var D = dur || totalTime || 1;
    var BUCKETS = 80;
    var bucketWpm = [];
    for (var bi = 0; bi < BUCKETS; bi++) {
      var t0 = bi / BUCKETS * D, t1 = (bi + 1) / BUCKETS * D;
      var wcount = 0, wtime = 0;
      parsed.forEach(function (seg) {
        var overlap = Math.min(seg.end, t1) - Math.max(seg.start, t0);
        if (overlap > 0) {
          var frac = overlap / seg.dur;
          wcount += seg.t.split(/\s+/).length * frac;
          wtime += overlap;
        }
      });
      bucketWpm.push(wtime > 0 ? wcount / (wtime / 60) : 0);
    }
    var maxWpmVal = Math.max.apply(null, bucketWpm) || 1;
    var energy = bucketWpm.map(function (v) { return parseFloat((v / maxWpmVal).toFixed(3)); });

    return { segs: parsed, spk: spk, D: D, energy: energy };
  }

  // ── Transcript: build segment HTML ─────────────────────────────────────────
  function buildTranscriptHtml(T, filterQ) {
    if (!T || !T.segs.length) return '<p class="empty">Leeg transcript.</p>';
    var q = filterQ ? filterQ.trim().toLowerCase() : '';
    var html = '';
    T.segs.forEach(function (seg) {
      if (q && seg.t.toLowerCase().indexOf(q) === -1) return;
      var c = colorFor(seg.sp);
      html += '<div class="seg" data-si="' + seg.i + '">'
        + '<button class="tbtn" type="button" data-seek="' + Math.round(seg.start) + '">'
        + ts(seg.start) + '</button>'
        + '<div><b style="color:' + c + '">' + esc(seg.sp) + '</b>'
        + '<p>' + esc(seg.t) + '</p></div></div>';
    });
    if (!html) html = '<p class="empty">Niets gevonden in dit transcript.</p>';
    return html;
  }

  // ── Transcript: render river into [data-river-pending] ─────────────────────
  function renderRiver(T) {
    var riverEl = document.querySelector('[data-river-pending]');
    if (!riverEl || !T) return;
    riverEl.removeAttribute('data-river-pending');
    riverEl.setAttribute('data-river', '');
    var D = T.D || 1;
    var html = T.segs.map(function (s) {
      var left = (s.start / D * 100).toFixed(2);
      var w = Math.max(0.1, (s.dur / D * 100)).toFixed(2);
      return '<i style="position:absolute;top:0;bottom:0;left:' + left + '%;width:' + w + '%;'
        + 'background:' + colorFor(s.sp) + '" title="' + ts(s.start) + ' · ' + s.sp + '"></i>';
    }).join('');
    html += '<b id="pl-head" style="position:absolute;top:0;bottom:0;width:2px;'
      + 'background:white;margin-left:-1px;left:0;pointer-events:none"></b>';
    riverEl.style.position = 'relative';
    riverEl.style.cursor = 'pointer';
    riverEl.innerHTML = html;

    riverEl.addEventListener('click', function (e) {
      var rect = riverEl.getBoundingClientRect();
      var pct = (e.clientX - rect.left) / rect.width;
      var seekT = Math.round(pct * D);
      if (window._PL && window._PL.audio) {
        window._PL.audio.currentTime = seekT;
        if (window._PL.audio.paused) window._PL.audio.play().catch(function () {});
      }
    });
  }

  // ── Transcript: render speakers legend into [data-spk-pending] ─────────────
  function renderSpk(T) {
    var spkEl = document.querySelector('[data-spk-pending]');
    if (!spkEl || !T) return;
    spkEl.removeAttribute('data-spk-pending');
    spkEl.innerHTML = T.spk.map(function (s) {
      return '<span><i style="display:inline-block;width:10px;height:10px;border-radius:999px;'
        + 'background:' + s.c + ';margin-right:5px;flex-shrink:0"></i>'
        + esc(s.name) + ' <span class="muted num">' + Math.round(s.share * 100) + '%</span></span>';
    }).join('');
  }

  // ── Transcript: lazy-load ───────────────────────────────────────────────────
  var _TX = null;
  var _txLoading = false;
  function loadTranscript() {
    if (_TX || _txLoading) return;
    _txLoading = true;
    var meta = document.getElementById('ep-meta');
    if (!meta) return;
    var key = meta.dataset.epKey;
    var dur = parseInt(meta.dataset.epDur, 10) || 0;
    if (!key) return;

    fetch('/data/transcripts/' + key + '.json')
      .then(function (r) {
        if (!r.ok) throw new Error('not found');
        return r.json();
      })
      .then(function (tr) {
        _TX = parseTranscript(tr, dur);

        // Fill transcript segs
        var segsEl = document.getElementById('segs');
        if (segsEl) segsEl.innerHTML = buildTranscriptHtml(_TX);

        // Render river and spk legend in Overzicht tab
        renderRiver(_TX);
        renderSpk(_TX);

        // Merge chapter start times from DOM into _TX so energySVG can mark them
        _TX.chapters = Array.from(document.querySelectorAll('.chapters li[data-ch]')).map(function (li) {
          var btn = li.querySelector('[data-seek]');
          return { start: btn ? parseInt(btn.dataset.seek, 10) : 0 };
        }).sort(function (a, b) { return a.start - b.start; });

        // Render analyse placeholder (actual stats require heavier computation)
        var anEl = document.querySelector('[data-analyse-pending]');
        if (anEl) {
          anEl.removeAttribute('data-analyse-pending');
          anEl.innerHTML = renderAnalyse(_TX);
        }

        // Wire transcript search
        var qEl = document.getElementById('tr-q');
        if (qEl) {
          qEl.addEventListener('input', function () {
            var segsEl2 = document.getElementById('segs');
            if (segsEl2) segsEl2.innerHTML = buildTranscriptHtml(_TX, qEl.value);
          });
        }

        // Inject langste monoloog into #hl-list (sorted by time)
        injectMonoloogHighlight(_TX);

        // Update player river if player already built
        if (window._PL) syncPlayerRiver(_TX);
      })
      .catch(function () {
        var segsEl = document.getElementById('segs');
        if (segsEl) segsEl.innerHTML = '<p class="muted">Transcript niet beschikbaar.</p>';
      });
  }

  // ── Hoogtepunten: inject langste monoloog from transcript ──────────────────
  function injectMonoloogHighlight(T) {
    var hlList = document.getElementById('hl-list');
    if (!hlList || !T || !T.segs.length) return;
    var mono = T.segs.reduce(function (best, s) { return s.dur > (best ? best.dur : 0) ? s : best; }, null);
    if (!mono) return;
    var mins = Math.max(1, Math.round(mono.dur / 60));
    var li = document.createElement('li');
    li.innerHTML = '<button class="tbtn" type="button" data-seek="' + Math.round(mono.start) + '">'
      + ts(mono.start) + '</button>'
      + '<div><span class="label">Langste monoloog · ' + esc(mono.sp) + '</span>'
      + '<p>' + esc(mono.sp) + ' aan het woord, ' + mins + ' minuten zonder onderbreking.</p></div>';
    // Insert at correct sorted position by data-seek value
    var items = Array.from(hlList.querySelectorAll('li'));
    var inserted = false;
    for (var i = 0; i < items.length; i++) {
      var btn = items[i].querySelector('[data-seek]');
      var t = btn ? parseInt(btn.dataset.seek, 10) : Infinity;
      if (mono.start < t) {
        hlList.insertBefore(li, items[i]);
        inserted = true;
        break;
      }
    }
    if (!inserted) hlList.appendChild(li);
  }

  // ── Analyse tab: helpers ────────────────────────────────────────────────────
  var TICS = ['eigenlijk', 'zeg maar', 'nou', 'weet je', 'in die zin', 'als het ware', 'precies', 'interessant'];

  function energySVG(T) {
    if (!T.energy || !T.energy.length) return '';
    var W = 720, h = 170, pl = 8, pr = 8, pt = 12, pb = 24;
    var iw = W - pl - pr, ih = h - pt - pb, D = T.D || 1;
    var X = function (t) { return pl + iw * t / D; };
    var Y = function (v) { return pt + ih - ih * v; };
    var pts = T.energy.map(function (v, i) { return [X(i / 79 * D), Y(v)]; });
    var s = '<svg class="c anchart" viewBox="0 0 ' + W + ' ' + h + '" role="img" aria-label="Energie door de aflevering">';
    (T.chapters || []).forEach(function (c) {
      s += '<line class="grid" x1="' + X(c.start).toFixed(1) + '" x2="' + X(c.start).toFixed(1) + '" y1="' + pt + '" y2="' + (pt + ih) + '"/>';
    });
    s += '<path d="M' + pl + ',' + (pt + ih) + ' L' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' L') + ' L' + (W - pr) + ',' + (pt + ih) + ' Z" fill="var(--gold)" fill-opacity=".35"/>';
    s += '<polyline class="line" points="' + pts.map(function (p) { return p[0].toFixed(1) + ',' + p[1].toFixed(1); }).join(' ') + '"/>';
    [0, 0.25, 0.5, 0.75, 1].forEach(function (f) {
      s += '<text x="' + X(f * D).toFixed(1) + '" y="' + (h - 6) + '" text-anchor="' + (f === 0 ? 'start' : f === 1 ? 'end' : 'middle') + '">' + ts(f * D) + '</text>';
    });
    return s + '</svg>';
  }

  // ── Analyse tab: stats from transcript ─────────────────────────────────────
  function renderAnalyse(T) {
    if (!T || !T.segs.length) return '<p class="prose muted" style="padding:16px 0">Analyse beschikbaar zodra het transcript geladen is.</p>';

    // Per-speaker word counts, WPM, longest segment, questions
    var spkWords = {}, spkLongest = {}, spkQuestions = {};
    T.spk.forEach(function (s) {
      spkWords[s.name] = 0;
      spkLongest[s.name] = null;
      spkQuestions[s.name] = 0;
    });
    T.segs.forEach(function (seg) {
      var w = seg.t.split(/\s+/).length;
      if (spkWords[seg.sp] !== undefined) {
        spkWords[seg.sp] += w;
        if (!spkLongest[seg.sp] || seg.dur > spkLongest[seg.sp].dur) spkLongest[seg.sp] = seg;
        if (/[?]\s*$/.test(seg.t)) spkQuestions[seg.sp] = (spkQuestions[seg.sp] || 0) + 1;
      }
    });

    var totalWords = T.segs.reduce(function (n, s) { return n + s.t.split(/\s+/).length; }, 0);
    var totalSecs = T.spk.reduce(function (a, s) { return a + s.time; }, 0) || 1;
    var wpm = Math.round(totalWords / (totalSecs / 60));
    var david = T.spk.find(function (s) { return s.name === 'David Boogerd'; });
    var davidQ = david ? (spkQuestions[david.name] || 0) : 0;

    // Count 'God' occurrences
    var godCount = T.segs.reduce(function (n, s) {
      return n + (s.t.match(/\bGod\b/gi) || []).length;
    }, 0);

    var html = '<div class="tiles"><div><b>' + totalWords.toLocaleString('nl') + '</b>'
      + '<span>woorden gesproken</span></div>'
      + '<div><b>' + wpm + '</b><span>woorden per minuut</span></div>'
      + (davidQ ? '<div><b>' + davidQ + '</b><span>vragen van David</span></div>' : '')
      + (godCount ? '<div><b>' + godCount + '×</b><span>het woord ‘God’</span></div>' : '')
      + '</div>';

    // Spreektijd
    html += '<h2>Spreektijd</h2>';
    var maxShare = Math.max.apply(null, T.spk.map(function (s) { return s.share; }));
    T.spk.forEach(function (s) {
      var pct = Math.round(s.share * 100);
      var barPct = maxShare > 0 ? Math.round(s.share / maxShare * 100) : 0;
      html += '<div class="hbar" style="margin-bottom:6px">'
        + '<div class="hbar-l" style="font-size:14px;min-width:120px">' + esc(s.name) + '</div>'
        + '<div class="hbar-b" style="flex:1;height:16px;background:var(--parchment-3);border-radius:4px;position:relative">'
        + '<div style="width:' + barPct + '%;height:100%;background:' + s.c + ';border-radius:4px"></div></div>'
        + '<div class="hbar-v" style="font-size:13px;min-width:36px;text-align:right">' + pct + '%</div></div>';
    });

    // Spreektempo (WPM per speaker)
    var spkWpm = T.spk.map(function (s) {
      return { name: s.name, c: s.c, wpm: s.time > 0 ? Math.round(spkWords[s.name] / (s.time / 60)) : 0 };
    }).filter(function (s) { return s.wpm > 0; });
    if (spkWpm.length) {
      html += '<h2>Spreektempo</h2>'
        + '<p class="ui muted" style="font-size:13px;margin:-4px 0 10px">Woorden per minuut in deze aflevering.</p>';
      var maxWpm = Math.max.apply(null, spkWpm.map(function (s) { return s.wpm; })) || 1;
      spkWpm.forEach(function (s) {
        var barPct = Math.round(s.wpm / maxWpm * 100);
        html += '<div class="hbar" style="margin-bottom:6px">'
          + '<div class="hbar-l" style="font-size:14px;min-width:120px">' + esc(s.name) + '</div>'
          + '<div class="hbar-b" style="flex:1;height:16px;background:var(--parchment-3);border-radius:4px;position:relative">'
          + '<div style="width:' + barPct + '%;height:100%;background:' + s.c + ';border-radius:4px"></div></div>'
          + '<div class="hbar-v" style="font-size:13px;min-width:36px;text-align:right">' + s.wpm + '</div></div>';
      });
    }

    // Verloop van het gesprek (energy SVG)
    var esvg = energySVG(T);
    if (esvg) {
      html += '<h2>Verloop van het gesprek</h2>'
        + '<p class="ui muted" style="font-size:13px;margin:-4px 0 0">Woorden per minuut door de aflevering (voortschrijdend gemiddelde). Verticale lijnen markeren hoofdstukken.</p>'
        + esvg;
    }

    // Stopwoordjes
    var ticsUsed = TICS.filter(function (t) { return T.spk.some(function (s) { return s.tics && s.tics[t] > 0; }); });
    if (ticsUsed.length) {
      var ticsHead = '<tr><th></th>' + T.spk.map(function (s) {
        return '<th style="color:' + s.c + '">' + esc(s.name.split(' ')[0]) + '</th>';
      }).join('') + '</tr>';
      var ticsBody = ticsUsed.map(function (t) {
        var mx = Math.max.apply(null, T.spk.map(function (s) { return (s.tics && s.tics[t]) || 0; }));
        return '<tr><td>\'' + t + '\'</td>' + T.spk.map(function (s) {
          var v = (s.tics && s.tics[t]) || 0;
          return '<td class="' + (v === mx && mx > 3 ? 'hot' : '') + '">' + (v || '·') + '</td>';
        }).join('') + '</tr>';
      }).join('');
      html += '<h2>Stopwoordjes</h2><div class="scroll"><table class="tics">'
        + '<thead>' + ticsHead + '</thead><tbody>' + ticsBody + '</tbody></table></div>';
    }

    // Woordenschat (type-token ratio)
    var spkTtr = T.spk;
    if (spkTtr.length) {
      html += '<h2>Woordenschat</h2>'
        + '<p class="ui muted" style="font-size:13px;margin:-4px 0 10px">Aandeel unieke inhoudswoorden (langer dan drie letters, zonder stopwoorden). Leestekens tellen niet mee. De uitkomst hangt ook af van hoeveel iemand spreekt.</p>';
      spkTtr.forEach(function (s) {
        var pct = Math.round(s.ttr * 100);
        var barPct = pct; // Fixed 0–100% scale, matching the SPA.
        html += '<div class="hbar" style="margin-bottom:6px">'
          + '<div class="hbar-l" style="font-size:14px;min-width:120px">' + esc(s.name) + '</div>'
          + '<div class="hbar-b" style="flex:1;height:16px;background:var(--parchment-3);border-radius:4px;position:relative">'
          + '<div style="width:' + barPct + '%;height:100%;background:' + s.c + ';border-radius:4px"></div></div>'
          + '<div class="hbar-v" style="font-size:13px;min-width:36px;text-align:right">' + pct + '%</div></div>';
      });
    }

    // Langste monoloog
    var monoRows = T.spk.filter(function (s) { return spkLongest[s.name]; }).map(function (s) {
      var seg = spkLongest[s.name];
      return '<div style="display:flex;gap:8px;align-items:baseline;margin-bottom:6px">'
        + '<button class="tbtn" type="button" data-seek="' + Math.round(seg.start) + '">' + ts(seg.start) + '</button>'
        + '<span style="font-size:14px;color:' + s.c + '">' + esc(s.name) + '</span>'
        + '<span class="ui muted" style="font-size:13px">' + Math.max(1, Math.round(seg.dur / 60)) + ' min aan één stuk</span>'
        + '</div>';
    });
    if (monoRows.length) {
      html += '<h2>Langste monoloog</h2><div>' + monoRows.join('') + '</div>';
    }

    return html;
  }

  // ── Player: sync river after transcript loads ───────────────────────────────
  function syncPlayerRiver(T) {
    var pscrub = document.querySelector('.pscrub');
    if (!pscrub) return;
    var D = T.D || 1;
    var riverHtml = T.segs.map(function (s) {
      var left = (s.start / D * 100).toFixed(2);
      var w = Math.max(0.1, (s.dur / D * 100)).toFixed(2);
      return '<i style="position:absolute;top:0;bottom:0;left:' + left + '%;width:' + w + '%;'
        + 'background:' + colorFor(s.sp) + '" title="' + ts(s.start) + ' · ' + s.sp + '"></i>';
    }).join('');
    riverHtml += '<b id="pl-head" style="position:absolute;top:0;bottom:0;width:2px;'
      + 'background:white;margin-left:-1px;left:' + (window._PL ? (window._PL.t / D * 100).toFixed(3) : '0') + '%;pointer-events:none"></b>';
    pscrub.innerHTML = riverHtml;
    // Re-bind scrub click
    pscrub.addEventListener('click', function (e) {
      var rect = pscrub.getBoundingClientRect();
      var pct = (e.clientX - rect.left) / rect.width;
      var seekT = Math.round(pct * D);
      if (window._PL && window._PL.audio) {
        window._PL.audio.currentTime = seekT;
        window._PL.t = seekT;
      }
    });
  }

  // ── Chapter tracking: highlight current chapter in player bar ───────────────
  var _chapters = null;
  function updatePlayerChapter(t) {
    if (!_chapters) {
      var items = Array.from(document.querySelectorAll('.chapters li[data-ch]'));
      if (!items.length) return;
      _chapters = items.map(function (li) {
        var btn = li.querySelector('[data-seek]');
        return { el: li, idx: parseInt(li.dataset.ch, 10), start: btn ? parseInt(btn.dataset.seek, 10) : 0 };
      });
      _chapters.sort(function (a, b) { return a.start - b.start; });
    }
    var ci = -1;
    for (var i = _chapters.length - 1; i >= 0; i--) {
      if (t >= _chapters[i].start) { ci = i; break; }
    }
    var chEl = document.getElementById('pl-ch');
    if (chEl) {
      if (ci >= 0) {
        var h3 = _chapters[ci].el.querySelector('h3');
        chEl.textContent = (_chapters[ci].idx + 1) + '. ' + (h3 ? h3.textContent : '');
      } else {
        chEl.textContent = '';
      }
    }
    _chapters.forEach(function (c, i) { c.el.classList.toggle('cur', i === ci); });
  }

  // ── Segment tracking: highlight current segment ─────────────────────────────
  function trackSegment(t) {
    if (!_TX || !_TX.segs.length) return;
    var segsEl = document.getElementById('segs');
    if (!segsEl) return;
    // Binary search for current segment
    var segs = _TX.segs;
    var lo = 0, hi = segs.length - 1, idx = 0;
    while (lo <= hi) {
      var mid = (lo + hi) >> 1;
      if (segs[mid].start <= t) { idx = mid; lo = mid + 1; }
      else hi = mid - 1;
    }
    var current = segs[idx];
    if (!current) return;
    var currentEl = segsEl.querySelector('.seg[data-si="' + current.i + '"]');
    if (!currentEl) return;

    // Toggle .on
    var prev = segsEl.querySelector('.seg.on');
    if (prev === currentEl) return;
    if (prev) prev.classList.remove('on');
    currentEl.classList.add('on');

    // Scroll if follow enabled and transcript tab visible
    var followCb = document.getElementById('tr-follow');
    var trPanel = document.querySelector('.tabp[data-p="tr"]');
    if (followCb && followCb.checked && trPanel && !trPanel.hidden) {
      var rect = currentEl.getBoundingClientRect();
      var containerRect = segsEl.getBoundingClientRect();
      if (rect.top < containerRect.top + 20 || rect.bottom > containerRect.bottom - 20) {
        currentEl.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
  }

  // ── Episode detail: player bar ──────────────────────────────────────────────
  function initPlayer() {
    var meta = document.getElementById('ep-meta');
    if (!meta) return;
    var mp3 = meta.dataset.mp3;
    var npo = meta.dataset.npo;
    var dur = parseInt(meta.dataset.epDur, 10) || 0;

    if (mp3) {
      buildPlayerBar(mp3, dur);
    } else {
      // No mp3 — keep the Luister button for NPO-only
      var btn = document.getElementById('luister-btn');
      if (btn && npo) {
        btn.addEventListener('click', function () {
          window.open(npo, '_blank', 'noopener');
        });
      }
    }
  }

  function buildPlayerBar(mp3, dur) {
    var bar = document.createElement('div');
    bar.id = 'static-player';
    bar.className = 'player';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Audiospeler');

    bar.innerHTML = '<audio id="pl-audio" preload="metadata"></audio>'
      + '<div class="wrap pl">'
      + '<button class="pbtn" id="pl-play" type="button" aria-label="Afspelen">'
      + '<svg viewBox="0 0 24 24" id="pl-ico"><path d="M7 4l13 8-13 8z"/></svg></button>'
      + '<div style="min-width:0;flex:1">'
      + '<div class="ptop"><span class="pch" id="pl-ch"></span>'
      + '<span class="pt"><span id="pl-t">0:00</span> / ' + ts(dur) + '</span></div>'
      + '<div class="pscrub" style="position:relative;height:18px;background:var(--engraving);'
      + 'border-radius:4px;cursor:pointer;overflow:hidden">'
      + '<b id="pl-head" style="position:absolute;top:0;bottom:0;width:2px;background:white;'
      + 'margin-left:-1px;left:0;pointer-events:none"></b></div>'
      + '</div>'
      + '<button class="prate" id="pl-rate" type="button" aria-label="Afspeelsnelheid">1×</button>'
      + '</div>';

    var main = document.querySelector('main');
    if (main) main.classList.add('has-player');
    document.body.appendChild(bar);

    var au = document.getElementById('pl-audio');
    au.src = mp3;
    au.preload = 'metadata';

    var RATES = [1, 1.5, 2];
    window._PL = { audio: au, t: 0, playing: false, rate: 1, D: dur, raf: 0 };
    var PL = window._PL;

    var playBtn = document.getElementById('pl-play');
    var rateBtn = document.getElementById('pl-rate');
    var timeEl = document.getElementById('pl-t');

    function updateHead() {
      var pct = PL.D ? (PL.t / PL.D * 100).toFixed(3) : 0;
      var heads = document.querySelectorAll('#pl-head');
      heads.forEach(function (h) { h.style.left = pct + '%'; });
    }

    function tick() {
      if (!PL || !PL.playing) return;
      if (PL.audio && !PL.audio.paused) PL.t = PL.audio.currentTime;
      if (timeEl) timeEl.textContent = ts(PL.t);
      updateHead();
      trackSegment(PL.t);
      updatePlayerChapter(PL.t);
      if (PL.playing) PL.raf = requestAnimationFrame(tick);
    }

    function setPlaying(v) {
      PL.playing = v;
      if (playBtn) {
        playBtn.querySelector('svg').innerHTML = v
          ? '<path d="M6 4h4v16H6zM14 4h4v16h-4z"/>'
          : '<path d="M7 4l13 8-13 8z"/>';
        playBtn.setAttribute('aria-label', v ? 'Pauzeer' : 'Afspelen');
      }
    }

    // Keep play button and raf loop in sync when audio starts/stops externally (e.g. seek handler)
    au.addEventListener('play', function () {
      if (!PL.playing) {
        PL.playing = true;
        setPlaying(true);
        PL.raf = requestAnimationFrame(tick);
      }
    });
    au.addEventListener('pause', function () {
      if (PL.playing) {
        cancelAnimationFrame(PL.raf);
        setPlaying(false);
      }
    });

    playBtn && playBtn.addEventListener('click', function () {
      if (PL.playing) {
        au.pause();
        cancelAnimationFrame(PL.raf);
        setPlaying(false);
      } else {
        au.play().catch(function () {});
        PL.raf = requestAnimationFrame(tick);
        setPlaying(true);
      }
    });

    rateBtn && rateBtn.addEventListener('click', function () {
      PL.rate = RATES[(RATES.indexOf(PL.rate) + 1) % RATES.length];
      au.playbackRate = PL.rate;
      rateBtn.textContent = PL.rate + '×';
    });

    au.addEventListener('timeupdate', function () {
      PL.t = au.currentTime;
      if (timeEl) timeEl.textContent = ts(PL.t);
      updateHead();
      trackSegment(PL.t);
      updatePlayerChapter(PL.t);
    });

    au.addEventListener('ended', function () {
      cancelAnimationFrame(PL.raf);
      setPlaying(false);
    });

    var scrub = bar.querySelector('.pscrub');
    scrub && scrub.addEventListener('click', function (e) {
      var rect = scrub.getBoundingClientRect();
      var pct = (e.clientX - rect.left) / rect.width;
      var seekT = Math.round(pct * PL.D);
      au.currentTime = seekT;
      PL.t = seekT;
      updateHead();
    });

    // If transcript already loaded, sync river into player scrubber
    if (_TX) syncPlayerRiver(_TX);
  }

  // ── Stats: word trend ───────────────────────────────────────────────────────
  function initWordTrend() {
    var wordsEl = document.getElementById('words');
    var trendEl = document.getElementById('trend');
    if (!wordsEl || !trendEl) return;
    var idx = null;
    var selected = new Set();

    fetch('/data/word_index.json').then(function (r) { return r.json(); })
      .then(function (data) {
        idx = data;
        var top = Object.entries(data.words || {})
          .sort(function (a, b) { return (b[1].c || 0) - (a[1].c || 0); })
          .slice(0, 40);
        wordsEl.innerHTML = '<p class="label" style="margin-bottom:8px">Klik een woord:</p>'
          + top.map(function (w) {
            return '<button class="chip" type="button" data-word="' + w[0] + '">'
              + w[0] + ' <span class="muted">' + w[1].c + '</span></button>';
          }).join('');
        wordsEl.addEventListener('click', function (e) {
          var btn = e.target.closest('[data-word]');
          if (!btn) return;
          var w = btn.dataset.word;
          if (selected.has(w)) { selected.delete(w); btn.classList.remove('on'); }
          else { selected.add(w); btn.classList.add('on'); }
          drawTrend();
        });
      }).catch(function () {
        wordsEl.innerHTML = '<p class="muted">Woordindex niet beschikbaar.</p>';
      });

    function drawTrend() {
      if (!selected.size || !idx) { trendEl.innerHTML = ''; return; }
      var years = idx.years || [];
      if (!years.length) return;
      var series = Array.from(selected).map(function (w) {
        var entry = (idx.words || {})[w] || {};
        var ydata = entry.y || {};
        return { label: w, values: years.map(function (yr) { return ydata[yr] || 0; }) };
      });
      var maxV = Math.max.apply(null, series.flatMap(function (s) { return s.values; }));
      if (!maxV) return;
      var W = 560, H = 180, pl = 32, pr = 8, pt = 14, pb = 24;
      var w = W - pl - pr, h = H - pt - pb;
      var yScale = function (v) { return pt + h - (v / maxV) * h; };
      var xScale = function (i) { return pl + (i / (years.length - 1)) * w; };
      var COLS = ['var(--violet)', 'var(--gold)', 'var(--teal)', 'var(--rose)'];
      var paths = series.map(function (s, si) {
        var d = s.values.map(function (v, i) {
          return (i === 0 ? 'M' : 'L') + xScale(i).toFixed(1) + ' ' + yScale(v).toFixed(1);
        }).join(' ');
        return '<path d="' + d + '" fill="none" stroke="' + COLS[si % COLS.length]
          + '" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>';
      });
      var xLabels = years.filter(function (_, i) { return i % 2 === 0; }).map(function (yr) {
        var i = years.indexOf(yr);
        return '<text x="' + xScale(i).toFixed(1) + '" y="' + (H - 4)
          + '" text-anchor="middle" font-size="10" fill="var(--ink-muted)">' + yr + '</text>';
      });
      var legend = series.map(function (s, si) {
        return '<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;'
          + 'font-size:13px"><span style="width:12px;height:3px;background:'
          + COLS[si % COLS.length] + ';display:inline-block"></span>' + s.label + '</span>';
      }).join('');
      trendEl.innerHTML = '<svg class="c" viewBox="0 0 ' + W + ' ' + H
        + '" style="width:100%;max-width:' + W + 'px;height:' + H + 'px">'
        + paths.join('') + xLabels.join('') + '</svg>'
        + '<div style="margin-top:8px">' + legend + '</div>';
    }
  }

  // ── Init ───────────────────────────────────────────────────────────────────
  initBiblePopup();

  if (page === 'home') {
    initRandom();
  }
  if (page === 'episodes') {
    initEpisodeFilter();
  }
  if (page === 'guests') {
    initGuestFilter();
  }
  if (page === 'persons') {
    initPersonsFilter();
  }
  if (page === 'books') {
    initBooksFilter();
  }
  if (page === 'episode') {
    initTabs();
    loadTranscript();
    initPlayer();
  }
  if (page === 'stats') {
    initWordTrend();
  }
})();
