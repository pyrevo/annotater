// Single source of truth for the AnnotateR citation shown and copied by the
// frontend. The values mirror the published release metadata (GitHub Release
// v0.1.0-rc3 and the Zenodo record) and the repository CITATION.cff.
//
// DOI policy (documented in docs/release-plan-0.1.0.md):
// - The general project citation uses the Zenodo *Concept* DOI, which is
//   version-independent and always resolves to the latest published release.
//   The in-app "Cite AnnotateR" button copies this general citation.
// - Citing one specific release uses the *version* DOI; that form is
//   available via formatVersionCitation() and shown in README.md.

export const CITATION = {
  title: 'AnnotateR',
  year: 2026,
  version: 'v0.1.0-rc3',
  authors: [
    { family: 'Das', given: 'Jyotirmoy' },
    { family: 'Volpe', given: 'Massimiliano' },
  ],
  conceptDoi: '10.5281/zenodo.23415801',
  versionDoi: '10.5281/zenodo.23415802',
  repository: 'https://github.com/pyrevo/annotater',
};

const authorList = () =>
  CITATION.authors.map(({ family, given }) => `${family}, ${given[0]}.`).join(' & ');

const doiUrl = (doi) => `https://doi.org/${doi}`;

// General project citation (Concept DOI, version-independent). This is what
// the in-app copy button writes to the clipboard.
export function formatCitation() {
  return `${authorList()} (${CITATION.year}). ${CITATION.title} [Computer software]. Zenodo. ${doiUrl(CITATION.conceptDoi)}`;
}

// Citation for one specific release (version DOI).
export function formatVersionCitation() {
  return `${authorList()} (${CITATION.year}). ${CITATION.title} (Version ${CITATION.version}) [Computer software]. Zenodo. ${doiUrl(CITATION.versionDoi)}`;
}

// Compact citation shown in the footer next to the copy button.
export function formatCitationShort() {
  return `${authorList()} (${CITATION.year}). ${CITATION.title}. ${doiUrl(CITATION.conceptDoi)}`;
}

// Write text to the clipboard without claiming success when the write failed.
// Returns true only when the clipboard write actually succeeded. The
// clipboard is injectable so the behaviour can be tested without a browser.
export async function copyCitation(text, clipboard = globalThis.navigator?.clipboard) {
  if (!clipboard || typeof clipboard.writeText !== 'function') return false;
  try {
    await clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
