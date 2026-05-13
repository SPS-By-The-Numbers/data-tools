// OSPI Apportionment / SAFS Reports scraper.
//
// Run from the browser JavaScript console on:
//   https://ospi.k12.wa.us/policy-funding/school-apportionment/safs-report
//
// Walks every applicable combination of #years, #report_types, #org_types,
// #orgs, #districts (each one optional) and downloads every document listed
// in #documents. Filenames are prefixed with the chosen labels at each
// level so files don't collide and are easy to sort.
//
// The page's safs_report.js binds delegated jQuery change handlers:
//   $(once('select', '#years'))       .on('change', 'select', refetches report_types/org_types/orgs)
//   $(once('select', '#report_types')).on('change', 'select', refetches org_types/orgs)
//   $(once('select', '#org_types'))   .on('change', 'select', refetches orgs)
//   $(once('select', '#orgs'))        .on('change', 'select', may fetch districts, may fetch documents)
//   $(once('select', '#districts'))   .on('change', 'select', fetches documents)
// Each XHR is bracketed by global $(document).ajaxSend / ajaxComplete, so we
// track inflight count and wait for it to stay at zero before sampling DOM.
//
// Some report types don't need org_type/org/district at all; their containers
// stay as empty <div>s (no <select> inside). The scraper detects this at each
// step and only iterates levels that actually have options.
//
// Before running, in Chrome go to Settings > Downloads and either pick a target
// directory or disable "Ask where to save", otherwise you'll get a prompt per
// file. Also allow "multiple downloads" if the site prompts.

(async () => {
  const $ = window.jQuery;
  if (!$) throw new Error('jQuery not found on page; this scraper depends on it.');

  const AJAX_QUIET_MS = 600;
  const AJAX_MAX_WAIT_MS = 60000;
  const POST_TRIGGER_PAUSE_MS = 100;
  const DOWNLOAD_GAP_MIN_MS = 250;
  const DOWNLOAD_GAP_MAX_MS = 1500;
  const MAX_CONCURRENT_DOWNLOADS = 4;

  const LEVELS = ['years', 'report_types', 'org_types', 'orgs', 'districts'];

  const jitteredGap = () => DOWNLOAD_GAP_MIN_MS
    + Math.random() * (DOWNLOAD_GAP_MAX_MS - DOWNLOAD_GAP_MIN_MS);

  const sanitize = (s) => s
    .replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 200);

  const docsDiv = document.getElementById('documents');
  if (!docsDiv) throw new Error('#documents container not found.');

  // Track inflight XHRs by hooking the page's own ajax events.
  let inflight = 0;
  $(document).on('ajaxSend.fundingScraper', () => { inflight++; });
  $(document).on('ajaxComplete.fundingScraper', () => { inflight--; });

  async function waitForAjaxIdle() {
    const start = Date.now();
    let quietSince = inflight === 0 ? Date.now() : null;
    while (Date.now() - start < AJAX_MAX_WAIT_MS) {
      if (inflight === 0) {
        if (quietSince === null) quietSince = Date.now();
        if (Date.now() - quietSince >= AJAX_QUIET_MS) return;
      } else {
        quietSince = null;
      }
      await new Promise(r => setTimeout(r, 50));
    }
    console.warn(`[waitForAjaxIdle] timed out after ${AJAX_MAX_WAIT_MS}ms, inflight=${inflight}`);
  }

  // Returns the <select> inside the container if one exists, otherwise null.
  // The org_types/orgs/districts containers start as empty <div>s and only get
  // a <select> injected when the previous level's AJAX response indicates
  // there's something to pick.
  const selectIn = (boxId) => {
    const box = document.getElementById(boxId);
    return box ? box.querySelector('select') : null;
  };

  const realOptions = (boxId) => {
    const sel = selectIn(boxId);
    if (!sel) return [];
    return [...sel.options]
      .filter(o => !o.disabled && o.value && o.value !== '0')
      .map(o => ({ value: o.value, label: o.textContent.trim() }));
  };

  function setSelect(boxId, value) {
    const sel = selectIn(boxId);
    if (!sel) throw new Error(`#${boxId} select not present`);
    const before = sel.value;
    $(sel).val(value).trigger('change');
    if (sel.value !== value) {
      console.warn(`[setSelect] ${boxId}: requested ${value}, got ${sel.value} (was ${before}). Skipping.`);
      return false;
    }
    return true;
  }

  // Pipelined download: jitter is paced from the START of each fetch, with
  // a hard ceiling of MAX_CONCURRENT_DOWNLOADS in flight at once. So fetch
  // times don't compound onto the throttle, but we still cap parallel load.
  async function downloadOne(url, filename) {
    try {
      // hostedreports.ospi.k12.wa.us returns Access-Control-Allow-Origin: *,
      // which browsers reject for credentialed CORS. The endpoint is public.
      const resp = await fetch(url, { credentials: 'omit' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      // Force octet-stream so Chrome saves rather than previews PDFs.
      const raw = await resp.arrayBuffer();
      const blob = new Blob([raw], { type: 'application/octet-stream' });
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
      console.error(`[fail] ${url} (${filename})`, err);
    }
  }

  async function downloadDocuments(prefix) {
    const links = [...docsDiv.querySelectorAll('a[href]')];
    if (links.length === 0) {
      console.log(`[skip] ${prefix} - no documents`);
      return;
    }
    let inflight = 0;
    const pending = [];
    for (const a of links) {
      const url = a.href;
      const origName = (a.textContent.trim() || url.split('/').pop()) || 'document';
      const filename = sanitize(`${prefix} - ${origName}`);
      while (inflight >= MAX_CONCURRENT_DOWNLOADS) {
        await new Promise(r => setTimeout(r, 50));
      }
      inflight++;
      pending.push(downloadOne(url, filename).finally(() => { inflight--; }));
      const gap = jitteredGap();
      console.log(`[start] ${filename} (${inflight} inflight, next in ${Math.round(gap)}ms)`);
      await new Promise(r => setTimeout(r, gap));
    }
    await Promise.allSettled(pending);
  }

  // Recursive cascade. At each level, set the chosen value, wait for AJAX to
  // settle, then look at the next level's container. If a select with real
  // options appeared, iterate it; otherwise the current path terminates with
  // a download of whatever is in #documents.
  let combosProcessed = 0;
  async function descend(levelIdx, prefixParts) {
    if (levelIdx >= LEVELS.length) {
      await downloadDocuments(prefixParts.join(' - '));
      combosProcessed++;
      return;
    }
    const boxId = LEVELS[levelIdx];
    const opts = realOptions(boxId);
    if (opts.length === 0) {
      // No select or no options for this level under the current prefix; that
      // means this report type / combination doesn't need this level, so we
      // terminate the cascade and download what's currently in #documents.
      await downloadDocuments(prefixParts.join(' - '));
      combosProcessed++;
      return;
    }

    console.group(`${boxId}: ${opts.length} option(s)`);
    for (const o of opts) {
      if (!setSelect(boxId, o.value)) continue;
      await new Promise(r => setTimeout(r, POST_TRIGGER_PAUSE_MS));
      await waitForAjaxIdle();
      await descend(levelIdx + 1, [...prefixParts, o.label]);
      if (combosProcessed && combosProcessed % 25 === 0) {
        console.log(`Progress: ${combosProcessed} combinations processed.`);
      }
    }
    console.groupEnd();
  }

  try {
    await descend(0, []);
    console.log(`Done. ${combosProcessed} combinations processed.`);
  } finally {
    $(document).off('ajaxSend.fundingScraper ajaxComplete.fundingScraper');
  }
})();
