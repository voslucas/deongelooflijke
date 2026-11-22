"""Keep static episode vocabulary compatible with the original SPA calculation."""
import pathlib
import shutil
import subprocess

import pytest


ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.skipif(not shutil.which('node'), reason='JavaScript runtime required')
def test_static_vocabulary_matches_spa():
    script = r"""
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const spa = fs.readFileSync('site/src/index.template.html', 'utf8');
const app = fs.readFileSync('site/src/app.js', 'utf8');
const context = vm.createContext({});
// Execute the real tokenizers and static parser, without starting the page UI.
vm.runInContext(spa.match(/^const STOP=.*$/m)[0] + '\n'
  + spa.match(/^const tok=.*$/m)[0] + '\n'
  + app.slice(app.indexOf('  var SPEAKER_COLORS'),
              app.indexOf('  // ── Transcript: build segment HTML')), context);
const fixtures = [
  {speakers: [{id: 'S1', name: 'David Boogerd'}], segments: [
    {speaker: 'S1', start: 0, end: 10,
     text: 'Geloof, geloof! Geloof? café CAFÉ. kerk-zijn kerk-zijn. Ik de mensen.'}
  ]},
  {speakers: [{id: 'S1', name: 'David Boogerd'}], segments: [
    {speaker: 'S1', start: 0, end: 10, text: 'Ik de en mensen 123 !!!'}
  ]}
];
// Include every available real transcript to catch speaker/segment differences.
for (const file of fs.readdirSync('data/transcripts').filter(f => f.endsWith('.json'))) {
  fixtures.push(JSON.parse(fs.readFileSync('data/transcripts/' + file, 'utf8')));
}
for (const raw of fixtures) {
  context.raw = raw;
  vm.runInContext(`
    parseTranscript(raw, 60).spk.forEach(s => {
      const ids = new Set((raw.speakers || []).filter(x => x.name === s.name).map(x => x.id));
      const words = raw.segments.filter(x => ids.has(x.speaker) || x.speaker === s.name)
        .flatMap(x => tok(x.text));
      const expected = words.length ? +(new Set(words).size / words.length).toFixed(3) : 0;
      if (s.ttr !== expected) throw new Error(s.name + ': ' + s.ttr + ' != ' + expected);
    });
  `, context);
}
assert.equal(vm.runInContext('parseTranscript(raw = ' + JSON.stringify(fixtures[0])
  + ', 60).spk[0].ttr', context), 0.429);
assert.equal(vm.runInContext('parseTranscript(raw = ' + JSON.stringify(fixtures[1])
  + ', 60).spk[0].ttr', context), 0);
console.log('Vocabulary parity verified for ' + fixtures.length + ' transcripts/fixtures');
"""
    result = subprocess.run(
        [shutil.which('node'), '-e', script], cwd=ROOT,
        capture_output=True, text=True, encoding='utf-8',
    )
    assert result.returncode == 0, result.stdout + result.stderr
