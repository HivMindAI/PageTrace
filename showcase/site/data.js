// Exact public synthetic texts from PORTFOLIO_PAGE_TEXTS. No customer data.
export const SOURCE_REVISION = '0de8da3556406c0b12d135fce806d1936e3cd9f6';
export const SOURCE_URL = `https://github.com/HivMindAI/PageTrace/blob/${SOURCE_REVISION}`;
export const SAMPLE_NAME = 'northstar-fy2025.pdf';
export const pages = Object.freeze([
  Object.freeze({
    number: 1,
    reference: 'sample-page-1',
    text: 'Northstar FY2025 revenue was $12.4 million, up 24 percent year over year.',
  }),
  Object.freeze({
    number: 2,
    reference: 'sample-page-2',
    text: 'Northstar FY2025 operating margin was 18 percent. Risks include supplier concentration.',
  }),
]);
export const examples = Object.freeze([
  { label: 'Revenue', query: 'Northstar FY2025 revenue?' },
  { label: 'Operating margin', query: 'Northstar FY2025 operating margin?' },
  { label: 'Try abstention', query: 'Carbon emissions target?' },
]);
