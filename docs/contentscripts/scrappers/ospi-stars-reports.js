// OSPI Student Transportation Allocation (STARS) Reports scraper.
//
// Run from the browser JavaScript console on:
//   https://ospi.k12.wa.us/policy-funding/student-transportation/student-transportation-allocation-reporting-system-stars/student-transportation-allocation-stars-reports
//
// Walks every (year, report_type, org) combination, waits for the #documents
// list to stop mutating, then fetches each document and re-downloads it via a
// Blob URL so the filename can be prefixed with the three selection labels.
//
// Before running, in Chrome go to Settings > Downloads and either pick a target
// directory or enable "Ask where to save" off, otherwise you'll get a prompt
// per file. Also allow "multiple downloads" if the site prompts.

(async () => {
  const SETTLE_MS = 3000;            // quiet period after last DOM mutation
  const MAX_WAIT_MS = 60000;         // hard cap per combination
  const POST_CHANGE_PAUSE_MS = 500;  // brief pause after dispatching change
  const DOWNLOAD_GAP_MIN_MS = 500;   // min jittered gap between downloads
  const DOWNLOAD_GAP_MAX_MS = 5000;  // max jittered gap between downloads

  const jitteredGap = () => DOWNLOAD_GAP_MIN_MS
    + Math.random() * (DOWNLOAD_GAP_MAX_MS - DOWNLOAD_GAP_MIN_MS);

  const yearsBox = document.querySelector('#years select');
  const reportsBox = document.querySelector('#report_types select');
  const orgsBox = document.querySelector('#orgs select');
  const docsDiv = document.querySelector('#documents');
  if (!yearsBox || !reportsBox || !orgsBox || !docsDiv) {
    throw new Error('Required form controls not found. Are you on the STARS page?');
  }

  const realOptions = (sel) => [...sel.options]
    .filter(o => !o.disabled && o.value && o.value !== '0')
    .map(o => ({ value: o.value, label: o.textContent.trim() }));

  const sanitize = (s) => s
    .replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 200);

  // The site is Drupal 10; change handlers are commonly attached via jQuery.
  // Native dispatchEvent(new Event('change')) usually works on jQuery handlers
  // because jQuery binds with addEventListener under the hood, but some legacy
  // bindings (and Drupal AJAX wrappers) only see jQuery-triggered events.
  // Prefer jQuery if present, then fall back to native.
  const setSelect = (sel, value) => {
    const before = sel.value;
    sel.focus();
    if (window.jQuery) {
      const $sel = window.jQuery(sel);
      $sel.val(value);
      $sel.trigger('input');
      $sel.trigger('change');
    } else {
      sel.value = value;
      sel.dispatchEvent(new Event('input', { bubbles: true }));
      sel.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (sel.value !== value) {
      console.warn(`[setSelect] ${sel.getAttribute('aria-label')}: requested ${value}, got ${sel.value} (was ${before}). Option may not exist for this combination.`);
    } else {
      console.log(`[setSelect] ${sel.getAttribute('aria-label')} = ${value} (was ${before})`);
    }
  };

  const docsSnapshot = () => docsDiv.innerHTML;

  // Resolve once #documents has been quiet for SETTLE_MS, or MAX_WAIT_MS hits.
  // The page often updates #documents 3+ times per change (spinner, partial,
  // final), so debounce on every mutation and only resolve when the dust settles.
  // Returns true if any mutation was observed at all, so callers can warn when
  // a change event apparently produced no AJAX response.
  const waitForSettle = () => new Promise((resolve) => {
    let mutationCount = 0;
    let quietTimer;
    const armQuietTimer = () => {
      clearTimeout(quietTimer);
      quietTimer = setTimeout(finish, SETTLE_MS);
    };
    const observer = new MutationObserver((records) => {
      mutationCount += records.length;
      armQuietTimer();
    });
    const hardTimer = setTimeout(finish, MAX_WAIT_MS);
    function finish() {
      observer.disconnect();
      clearTimeout(quietTimer);
      clearTimeout(hardTimer);
      resolve(mutationCount);
    }
    observer.observe(docsDiv, { childList: true, subtree: true, characterData: true });
    armQuietTimer();
  });

  async function downloadDocuments(prefix) {
    const links = [...docsDiv.querySelectorAll('a[href]')];
    if (links.length === 0) {
      console.log(`[skip] ${prefix} - no documents`);
      return;
    }
    for (const a of links) {
      const url = a.href;
      const origName = (a.textContent.trim() || url.split('/').pop()) || 'document';
      const filename = sanitize(`${prefix} - ${origName}`);
      try {
        const resp = await fetch(url, { credentials: 'include' });
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const blob = await resp.blob();
        const blobUrl = URL.createObjectURL(blob);
        const trigger = document.createElement('a');
        trigger.href = blobUrl;
        trigger.download = filename;
        document.body.appendChild(trigger);
        trigger.click();
        trigger.remove();
        URL.revokeObjectURL(blobUrl);
        console.log(`[ok] ${filename}`);
      } catch (err) {
        console.error(`[fail] ${url} (${prefix})`, err);
      }
      const gap = jitteredGap();
      console.log(`[wait] ${Math.round(gap)}ms`);
      await new Promise(r => setTimeout(r, gap));
    }
  }

  const years = realOptions(yearsBox);
  const reportTypes = realOptions(reportsBox);
  console.log(`Iterating ${years.length} year(s) x ${reportTypes.length} report type(s); orgs vary per combination.`);

  let combosProcessed = 0;
  for (const y of years) {
    for (const r of reportTypes) {
      console.group(`year=${y.label}  report=${r.label}`);
      setSelect(yearsBox, y.value);
      setSelect(reportsBox, r.value);
      await new Promise(res => setTimeout(res, POST_CHANGE_PAUSE_MS));
      await waitForSettle();

      const orgsContainer = document.querySelector('#orgs');
      const orgsHidden = orgsContainer && orgsContainer.offsetParent === null;
      const orgs = realOptions(orgsBox);

      if (orgsHidden || orgs.length === 0) {
        await downloadDocuments(`${y.label} - ${r.label}`);
        combosProcessed++;
      } else {
        for (const o of orgs) {
          setSelect(orgsBox, o.value);
          await new Promise(res => setTimeout(res, POST_CHANGE_PAUSE_MS));
          await waitForSettle();
          await downloadDocuments(`${y.label} - ${r.label} - ${o.label}`);
          combosProcessed++;
          if (combosProcessed % 25 === 0) {
            console.log(`Progress: ${combosProcessed} combinations processed.`);
          }
        }
      }
      console.groupEnd();
    }
  }
  console.log(`Done. ${combosProcessed} combinations processed.`);
})();
