import { answer as generateAnswer } from './engine.js';
import { pages, examples, SOURCE_URL } from './data.js';

/** @typedef {import('./engine.js').DemoResult} DemoResult */

/** @param {string} selector @returns {HTMLElement} */
function required(selector) {
  const element = document.querySelector(selector);
  if (!(element instanceof HTMLElement)) throw new Error(`Missing element: ${selector}`);
  return element;
}

/** @template {keyof HTMLElementTagNameMap} K @param {K} tag @param {string} [text] @param {string} [className] */
function node(tag, text = '', className = '') {
  const element = document.createElement(tag);
  element.textContent = text;
  element.className = className;
  return element;
}

const question = document.querySelector('#question');
const coverage = document.querySelector('#coverage');
if (!(question instanceof HTMLInputElement) || !(coverage instanceof HTMLSelectElement)) throw new Error('Missing search controls');
const questionInput = question;
const coverageInput = coverage;
let currentResult = generateAnswer(examples[0].query);

/** @param {number} number @param {DemoResult['citation']} [citation] @param {boolean} [focus] */
function showPage(number, citation = null, focus = false) {
  const page = pages.find(page => page.number === number);
  if (!page) return;
  required('#preview-title').textContent = number === 1 ? 'Revenue statement' : 'Margin & risk statement';
  required('#page-number').textContent = `0${number} / 02`;
  required('#page-reference').textContent = page.reference;
  const paragraph = required('#page-text');
  paragraph.replaceChildren();
  if (citation && citation.hit.page.number === number) {
    paragraph.append(document.createTextNode(page.text.slice(0, citation.start)), node('mark', page.text.slice(citation.start, citation.end)), document.createTextNode(page.text.slice(citation.end)));
  } else {
    paragraph.textContent = page.text;
  }
  document.querySelectorAll('[data-page]').forEach(button => button.setAttribute('aria-pressed', String(button.getAttribute('data-page') === String(number))));
  if (focus) {
    const preview = required('#document-page');
    preview.focus({ preventScroll: true });
    preview.scrollIntoView({ block: 'center', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth' });
  }
}

/** @param {string} label @param {string} value */
function detail(label, value) {
  const entry = node('div');
  entry.append(node('dt', label), node('dd', value));
  return entry;
}

/** @param {number} number @param {string} text @param {DemoResult['citation']} [citation] */
function sourceLink(number, text, citation = null) {
  const link = node('a', text, 'citation-link');
  link.href = '#document-page';
  link.addEventListener('click', event => {
    event.preventDefault();
    showPage(number, citation, true);
  });
  return link;
}

/** @param {DemoResult} result */
function renderResult(result) {
  const root = required('#result');
  const header = node('div', '', 'result-header');
  header.append(node('span', 'Browser illustration / Result', 'eyebrow'), node('span', result.status, `status-badge ${result.status}`));
  const content = node('div', '', `answer-quote${result.citation ? '' : ' abstention-copy'}`);
  root.replaceChildren(header);
  if (result.citation) {
    const citation = result.citation;
    content.append(node('p', citation.excerpt));
    root.append(content, node('p', 'One exact excerpt. No generated wording.', 'answer-subtitle'));
    const evidence = node('div', '', 'citation');
    const top = node('div', '', 'citation-top');
    top.append(node('b', '01 / Source evidence'), sourceLink(citation.hit.page.number, `View page ${citation.hit.page.number} ↗`, citation));
    const details = node('dl');
    details.append(detail('Sample reference', citation.hit.page.reference), detail('Character offsets', `[${citation.start}, ${citation.end})`), detail('Retrieval rank', String(citation.hit.rank)), detail('Lexical coverage', `${citation.matched.length}/${result.terms.length} query terms`));
    evidence.append(top, node('p', citation.excerpt), details);
    root.append(evidence, node('p', 'Offsets are zero-based, end-exclusive, in the bundled page text. Lexical coverage is not a truth or confidence score.', 'coverage-note'));
    showPage(citation.hit.page.number, citation);
  } else {
    content.append(node('h4', 'Not enough evidence to answer.'));
    content.append(node('p', result.hits.length ? 'A page shares some query words, but no excerpt from the top page meets the selected coverage threshold.' : 'The sample contains no matching words for this question. PageTrace’s documented approach abstains when retrieval finds no evidence.'));
    content.append(node('code', result.reason ?? '', 'reason'));
    root.append(content, node('p', 'No answer and no citations. Try “revenue” or “operating margin” to explore evidence that is present.', 'answer-subtitle'));
    showPage(1);
  }
  const retrieval = node('details', '', 'retrieval');
  retrieval.open = true;
  retrieval.append(node('summary', `Document search · ${result.hits.length} matching page${result.hits.length === 1 ? '' : 's'}`));
  if (result.hits.length) {
    const list = node('ol');
    result.hits.forEach(hit => {
      const item = node('li');
      const heading = node('div', '', 'hit-title');
      heading.append(sourceLink(hit.page.number, `Page ${hit.page.number} · ${hit.page.reference}`), node('small', `BM25 ${hit.score.toFixed(3)}`));
      item.append(heading, node('p', hit.page.text), node('div', `Matched: ${hit.matched.join(' · ')}`, 'matched-terms'));
      list.append(item);
    });
    retrieval.append(list);
  } else {
    retrieval.append(node('p', 'No matching pages in the two-page sample.', 'empty-hits'));
  }
  retrieval.append(node('p', 'Browser BM25 illustration · k1 = 1.2 · b = 0.75. Scores rank word overlap; they are not Python evaluation results.', 'coverage-note'));
  root.append(retrieval);
}

function runSearch() {
  const error = required('#input-error');
  try {
    currentResult = generateAnswer(questionInput.value.trim(), Number(coverageInput.value));
    error.hidden = true;
    error.textContent = '';
    questionInput.removeAttribute('aria-invalid');
    required('#result').hidden = false;
    renderResult(currentResult);
  } catch (failure) {
    error.textContent = failure instanceof Error ? failure.message : 'The question could not be searched.';
    error.hidden = false;
    questionInput.setAttribute('aria-invalid', 'true');
    // Do not leave an old answer associated with an invalid new question.
    required('#result').hidden = true;
    showPage(1);
    questionInput.focus();
  }
}

required('#search-form').addEventListener('submit', event => {
  event.preventDefault();
  runSearch();
});
coverageInput.addEventListener('change', runSearch);
questionInput.addEventListener('input', () => {
  // An old result must not appear to answer a newly edited question.
  required('#result').hidden = true;
  required('#input-error').hidden = true;
  questionInput.removeAttribute('aria-invalid');
  showPage(1);
});
document.querySelectorAll('[data-example]').forEach(button => {
  button.addEventListener('click', () => {
    const example = examples[Number(button.getAttribute('data-example'))];
    if (!example) return;
    questionInput.value = example.query;
    runSearch();
  });
});
document.querySelectorAll('[data-page]').forEach(button => {
  button.addEventListener('click', () => showPage(Number(button.getAttribute('data-page')), required('#result').hidden ? null : currentResult.citation));
});

// Pin documentation to the inspected revision so claims remain reviewable.
document.querySelectorAll('a[data-doc]').forEach(link => {
  link.setAttribute('href', `${SOURCE_URL}/${link.getAttribute('data-doc')}`);
});

const navLinks = [...document.querySelectorAll('.primary-nav a')];
const observer = new IntersectionObserver(entries => {
  const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top)[0];
  if (!visible) return;
  navLinks.forEach(link => {
    if (link.getAttribute('href') === `#${visible.target.id}`) link.setAttribute('aria-current', 'location');
    else link.removeAttribute('aria-current');
  });
}, { rootMargin: '-5% 0px -60% 0px', threshold: 0 });
document.querySelectorAll('main > section[id]').forEach(section => observer.observe(section));

// Generated at development time from the exact deterministic PDF bytes.
import { pdfSha256 } from './sample-identity.js';
required('#source-digest').textContent = pdfSha256;
renderResult(currentResult);
