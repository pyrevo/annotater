import test from 'node:test';
import assert from 'node:assert/strict';

import {
  CITATION,
  formatCitation,
  formatVersionCitation,
  formatCitationShort,
  copyCitation,
} from './citation.js';

test('citation names the software and both authors in order', () => {
  const text = formatCitation();
  assert.match(text, /AnnotateR/);
  assert.match(text, /Das, J\./);
  assert.match(text, /Volpe, M\./);
  assert.ok(text.indexOf('Das') < text.indexOf('Volpe'), 'Das must precede Volpe');
});

test('general citation uses the Zenodo Concept DOI', () => {
  const text = formatCitation();
  assert.ok(text.includes(CITATION.conceptDoi));
  assert.ok(text.includes(`https://doi.org/${CITATION.conceptDoi}`));
});

test('version-specific citation uses the RC3 version DOI and version', () => {
  const text = formatVersionCitation();
  assert.ok(text.includes(CITATION.versionDoi));
  assert.ok(text.includes(CITATION.version));
  assert.ok(text.includes('Version v0.1.0-rc3'));
});

test('citations contain no placeholder text', () => {
  for (const text of [formatCitation(), formatVersionCitation(), formatCitationShort()]) {
    assert.doesNotMatch(text, /TBD|TODO|placeholder|XXX|citation here/i);
  }
});

test('short footer citation uses the Concept DOI and stays compact', () => {
  const text = formatCitationShort();
  assert.ok(text.includes(CITATION.conceptDoi));
  assert.ok(!text.includes('[Computer software]'));
});

test('copyCitation returns true when the clipboard write succeeds', async () => {
  const writes = [];
  const clipboard = { writeText: async (t) => writes.push(t) };
  const ok = await copyCitation('hello', clipboard);
  assert.equal(ok, true);
  assert.deepEqual(writes, ['hello']);
});

test('copyCitation returns false when the clipboard write rejects', async () => {
  const clipboard = { writeText: async () => { throw new Error('denied'); } };
  assert.equal(await copyCitation('hello', clipboard), false);
});

test('copyCitation returns false when no clipboard is available', async () => {
  assert.equal(await copyCitation('hello', undefined), false);
  assert.equal(await copyCitation('hello', {}), false);
});
