// Table column names as a resident reads them, matching the Word and PDF reports.
const LABELS = { n: 'N', sd: 'SD', pct: '%', mean_ci_low: 'Mean CI low', mean_ci_high: 'Mean CI high', median_ci_low: 'Median CI low', median_ci_high: 'Median CI high' }

export const columnLabel = (key) => LABELS[key] || (key.charAt(0).toUpperCase() + key.slice(1).replace(/_/g, ' '))
