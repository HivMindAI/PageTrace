import test from 'node:test';
import assert from 'node:assert/strict';
import { answer, search, sentenceSpans, tokenize } from '../site/engine.js';
import { pages, examples } from '../site/data.js';

test('documented revenue example returns the exact first page with inspectable offsets', () => {
  const result = answer(examples[0].query);
  assert.equal(result.status, 'answered');
  assert.equal(result.answer, pages[0].text);
  assert.equal(result.citation.hit.page.number, 1);
  assert.deepEqual([result.citation.start, result.citation.end], [0, pages[0].text.length]);
  assert.equal(result.citation.coverage, 1);
});

test('documented carbon example abstains without fabricated text or citations', () => {
  const result = answer(examples[2].query);
  assert.equal(result.status, 'abstained');
  assert.equal(result.reason, 'no_retrieval_hits');
  assert.equal(result.answer, null);
  assert.equal(result.citation, null);
  assert.deepEqual(result.hits, []);
});

test('operating margin selects its sentence and excludes the separate risk statement', () => {
  const result = answer(examples[1].query);
  assert.equal(result.answer, 'Northstar FY2025 operating margin was 18 percent.');
  assert.equal(result.citation.hit.page.number, 2);
});

test('risk evidence retains its nonzero source offsets', () => {
  const result = answer('supplier concentration');
  assert.equal(result.answer, 'Risks include supplier concentration.');
  assert.equal(result.citation.start, pages[1].text.indexOf('Risks'));
  assert.equal(result.citation.hit.page.text.slice(result.citation.start, result.citation.end), result.answer);
});

test('decimal punctuation is preserved and whitespace offsets stay exact', () => {
  const text = '  Revenue $12.4 million.\n  Risk!  ';
  assert.deepEqual(sentenceSpans(text).map(span => text.slice(span.start, span.end)), ['Revenue $12.4 million.', 'Risk!']);
  assert.equal(answer('12.4 million').answer, pages[0].text);
});

test('weak lexical overlap abstains even when a search hit exists', () => {
  const result = answer('Northstar climate emissions decarbonization target transition');
  assert.ok(result.hits.length > 0);
  assert.equal(result.reason, 'insufficient_query_term_coverage');
  assert.equal(result.answer, null);
  assert.equal(result.citation, null);
});

test('coverage setting changes eligibility without changing or inventing the source', () => {
  assert.equal(answer('revenue unknown', 0.5).answer, pages[0].text);
  assert.equal(answer('revenue unknown', 1).reason, 'insufficient_query_term_coverage');
});

test('normalization handles fixture case, fullwidth text, and duplicate query words', () => {
  assert.deepEqual(tokenize('ＮＯＲＴＨＳＴＡＲ FY2025'), ['northstar', 'fy2025']);
  assert.equal(answer('REVENUE revenue Revenue').citation.coverage, 1);
  assert.equal(search('revenue').hits[0].page.number, 1);
});

test('empty, term-free, oversized queries and invalid thresholds fail explicitly', () => {
  for (const query of ['', '   ', '?!—', 'x'.repeat(501)]) assert.throws(() => answer(query));
  for (const threshold of [0, -1, 1.1, NaN, Infinity]) assert.throws(() => answer('revenue', threshold));
});

test('all supported matrix answers reconstruct exactly from their sole citation', () => {
  for (const query of ['revenue', 'margin', 'supplier concentration', 'Northstar', 'FY2025', 'percent', 'million', 'unknown', 'carbon target', 'revenue future forecast']) {
    const result = answer(query);
    assert.deepEqual(answer(query), result);
    if (!result.citation) { assert.equal(result.answer, null); continue; }
    const { citation } = result;
    assert.equal(result.answer, citation.hit.page.text.slice(citation.start, citation.end));
    assert.ok(citation.coverage >= result.threshold);
    assert.ok(citation.matched.every(term => result.terms.includes(term)));
  }
});

test('retrieval scores are positive and ties preserve page ordering', () => {
  const hits = search('Northstar').hits;
  assert.ok(hits.every(hit => hit.score > 0));
  assert.ok(hits[0].score >= hits[1].score);
  assert.deepEqual(hits.map(hit => hit.rank), [1, 2]);
});
