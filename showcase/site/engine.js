/**
 * Browser-only illustration of the documented BM25 + exact-slice approach.
 * This searches two fixture pages, not Python corpus artifacts. JS lowercasing
 * is intentionally not described as Python Unicode casefold equivalence.
 */
import { pages } from './data.js';

/** @typedef {typeof pages[number]} SamplePage */
/** @typedef {{page: SamplePage, matched: string[], score: number, rank: number}} Hit */
/** @typedef {{start: number, end: number, excerpt: string, matched: string[], coverage: number, hit: Hit}} Citation */
/** @typedef {{query: string, terms: string[], hits: Hit[], threshold: number, status: 'answered' | 'abstained', answer: string | null, citation: Citation | null, reason: 'no_retrieval_hits' | 'insufficient_query_term_coverage' | null}} DemoResult */

/** @param {string} text @returns {string[]} */
export function tokenize(text) {
  return text.normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+(?:['’][\p{L}\p{N}]+)*/gu) ?? [];
}

/** @param {string} text @returns {{start: number, end: number}[]} */
export function sentenceSpans(text) {
  /** @type {{start: number, end: number}[]} */
  const spans = [];
  let start = 0;
  /** @param {number} end */
  function add(end) {
    while (start < end && /\s/u.test(text[start])) start++;
    while (end > start && /\s/u.test(text[end - 1])) end--;
    if (start < end) spans.push({ start, end });
  }
  for (let i = 0; i < text.length; i++) {
    const line = /[\r\n]/u.test(text[i]);
    const terminal = /[.!?]/u.test(text[i]) && (i + 1 === text.length || /\s/u.test(text[i + 1]));
    if (line || terminal) {
      add(line ? i : i + 1);
      start = i + 1;
    }
  }
  add(text.length);
  return spans;
}

/** @param {string} query */
export function search(query) {
  if (query.length > 500) throw new Error('Please keep your question to 500 characters.');
  const terms = [...new Set(tokenize(query))].sort();
  if (!terms.length) throw new Error('Enter a question with at least one word or number.');
  const tokenized = pages.map(page => tokenize(page.text));
  const average = tokenized.reduce((sum, tokens) => sum + tokens.length, 0) / pages.length;
  const hits = pages.map((page, index) => {
    const tokens = tokenized[index];
    const matched = terms.filter(term => tokens.includes(term));
    const score = matched.reduce((sum, term) => {
      const frequency = tokens.filter(token => token === term).length;
      const documents = tokenized.filter(tokens => tokens.includes(term)).length;
      const idf = Math.log(1 + (pages.length - documents + 0.5) / (documents + 0.5));
      return sum + idf * (frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * tokens.length / average)));
    }, 0);
    return { page, matched, score: Math.round(score * 1e12) / 1e12, rank: 0 };
  }).filter(hit => hit.score > 0).sort((a, b) => b.score - a.score || a.page.number - b.page.number);
  hits.forEach((hit, index) => { hit.rank = index + 1; });
  return { query, terms, hits };
}

/** @param {string} query @param {number} [threshold] @returns {DemoResult} */
export function answer(query, threshold = 0.5) {
  if (!Number.isFinite(threshold) || threshold <= 0 || threshold > 1) throw new Error('Invalid coverage threshold.');
  const retrieval = search(query);
  // One top page / one exact sentence, matching the portfolio's bounded setup.
  const candidates = retrieval.hits.slice(0, 1).flatMap(hit => sentenceSpans(hit.page.text).map(span => {
    const excerpt = hit.page.text.slice(span.start, span.end);
    const matched = retrieval.terms.filter(term => tokenize(excerpt).includes(term));
    return { ...span, excerpt, matched, coverage: matched.length / retrieval.terms.length, hit };
  })).filter(item => item.matched.length && item.coverage >= threshold)
    .sort((a, b) => b.coverage - a.coverage || a.start - b.start);
  /** @type {typeof candidates[number] | null} */
  const citation = candidates.length ? candidates[0] : null;
  const reason = !retrieval.hits.length ? 'no_retrieval_hits' : 'insufficient_query_term_coverage';
  return {
    ...retrieval,
    threshold,
    status: citation ? 'answered' : 'abstained',
    answer: citation?.excerpt ?? null,
    citation,
    reason: citation ? null : reason,
  };
}
