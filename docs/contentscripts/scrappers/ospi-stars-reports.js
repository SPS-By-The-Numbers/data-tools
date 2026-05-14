// OSPI Student Transportation Allocation (STARS) Reports scraper.
//
// Run from the browser JavaScript console on:
//   https://ospi.k12.wa.us/policy-funding/student-transportation/student-transportation-allocation-reporting-system-stars/student-transportation-allocation-stars-reports
//
// Walks every (year, report_type, org) combination, waits for the page's
// jQuery AJAX traffic to settle, then fetches each document in the #documents
// div and re-downloads it via a Blob URL so the filename can be prefixed with
// the three selection labels.
//
// Mechanics: the page's stars_report.js binds delegated jQuery change handlers:
//   $(once('select', '#years'))       .on('change', 'select', () => { getReportTypes(); getOrgs(); });
//   $(once('select', '#report_types')).on('change', 'select', () => { getOrgs(); });
//   $(once('select', '#orgs'))        .on('change', 'select', () => { getDocuments(); });
// We trigger change via jQuery (so delegated handlers fire) and wait on global
// $(document).ajaxSend / ajaxComplete events to know when the cascading AJAX
// is finished.
//
// Before running, in Chrome go to Settings > Downloads and either pick a target
// directory or disable "Ask where to save", otherwise you'll get a prompt per
// file. Also allow "multiple downloads" if the site prompts.

(async () => {
  const $ = window.jQuery;
  if (!$) throw new Error('jQuery not found on page; this scraper depends on it.');

  const AJAX_QUIET_MS = 600;         // require this much idle before considering AJAX done
  const AJAX_MAX_WAIT_MS = 60000;    // hard cap per wait
  const POST_TRIGGER_PAUSE_MS = 100; // let jQuery start the XHR before we sample inflight
  const DOWNLOAD_GAP_MIN_MS = 100;   // jittered gap between download starts
  const DOWNLOAD_GAP_MAX_MS = 750;
  const MAX_CONCURRENT_DOWNLOADS = 4;

  const jitteredGap = () => DOWNLOAD_GAP_MIN_MS
    + Math.random() * (DOWNLOAD_GAP_MAX_MS - DOWNLOAD_GAP_MIN_MS);

  const sanitize = (s) => s
    .replace(/[\\/:*?"<>|\x00-\x1f]+/g, '_')
    .replace(/\s+/g, ' ')
    .trim()
    .slice(0, 200);

  const docsDiv = document.getElementById('documents');
  if (!docsDiv) throw new Error('#documents container not found.');

  // The page fires $(document).ajaxSend / ajaxComplete around every XHR.
  // Track page XHR inflight count and wait until it stays at 0 for AJAX_QUIET_MS.
  let pageXhrInflight = 0;
  $(document).on('ajaxSend.starsScraper', () => { pageXhrInflight++; });
  $(document).on('ajaxComplete.starsScraper', () => { pageXhrInflight--; });

  async function waitForAjaxIdle() {
    const start = Date.now();
    let quietSince = pageXhrInflight === 0 ? Date.now() : null;
    while (Date.now() - start < AJAX_MAX_WAIT_MS) {
      if (pageXhrInflight === 0) {
        if (quietSince === null) quietSince = Date.now();
        if (Date.now() - quietSince >= AJAX_QUIET_MS) return;
      } else {
        quietSince = null;
      }
      await new Promise(r => setTimeout(r, 50));
    }
    console.warn(`[waitForAjaxIdle] timed out after ${AJAX_MAX_WAIT_MS}ms, inflight=${pageXhrInflight}`);
  }

  function realOptions(boxId) {
    const sel = document.querySelector(`#${boxId} select`);
    if (!sel) return [];
    return [...sel.options]
      .filter(o => !o.disabled && o.value && o.value !== '0')
      .map(o => ({ value: o.value, label: o.textContent.trim() }));
  }

  function setSelect(boxId, value) {
    const sel = document.querySelector(`#${boxId} select`);
    if (!sel) throw new Error(`#${boxId} select not found`);
    const before = sel.value;
    // Use jQuery val + trigger so the delegated change handlers fire.
    $(sel).val(value).trigger('change');
    if (sel.value !== value) {
      console.warn(`[setSelect] ${boxId}: requested ${value}, got ${sel.value} (was ${before}). Option missing for current combination.`);
      return false;
    }
    return true;
  }

  // Pipelined download: jitter is paced from the START of each fetch, with
  // a hard ceiling of MAX_CONCURRENT_DOWNLOADS in flight at once. So fetch
  // times don't compound onto the throttle, but we still cap parallel load.
  async function downloadOne(url, filename) {
    try {
      // credentials: 'omit' is required: hostedreports.ospi.k12.wa.us returns
      // Access-Control-Allow-Origin: * which the browser refuses to honor for
      // credentialed CORS requests. The endpoint is public, so no cookies needed.
      const resp = await fetch(url, { credentials: 'omit' });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      // Wrap in an octet-stream Blob so the browser saves instead of opening
      // the PDF in its built-in viewer. The original Blob carries the
      // application/pdf MIME, which Chrome's PDF handler can intercept even
      // when the anchor has a download attribute.
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

  // Global pipeline: inflight + pending live outside downloadDocuments so that
  // downloads from one combo overlap with the next combo's cascade work. The
  // outer cascade only blocks here when MAX_CONCURRENT_DOWNLOADS is reached.
  let inflight = 0;
  const pending = [];

  async function downloadDocuments(prefix) {
    const links = [...docsDiv.querySelectorAll('a[href]')];
    if (links.length === 0) {
      console.log(`[skip] ${prefix} - no documents`);
      return;
    }
    // Snapshot href + name immediately; the outer cascade will mutate
    // #documents (replace its contents on the next setSelect), but the URLs
    // we've captured here keep working.
    const items = links.map(a => ({
      url: a.href,
      name: sanitize(`${prefix} - ${(a.textContent.trim() || a.href.split('/').pop()) || 'document'}`),
    }));
    for (const { url, name } of items) {
      while (inflight >= MAX_CONCURRENT_DOWNLOADS) {
        await new Promise(r => setTimeout(r, 50));
      }
      inflight++;
      pending.push(downloadOne(url, name).finally(() => { inflight--; }));
      const gap = jitteredGap();
      console.log(`[start] ${name} (${inflight} inflight, next in ${Math.round(gap)}ms)`);
      await new Promise(r => setTimeout(r, gap));
    }
  }

  // Optional range bounds: set window.OSPI_SCRAPER_START and/or
  // window.OSPI_SCRAPER_END before running the loader to bracket the cascade.
  // Both bounds are CLOSED (inclusive) in the page's option order, so a run
  // with START={years:'2023', report_types:'14', orgs:'3247'} and END={years:
  // '2024', report_types:'14'} processes everything from (2023, 14, 3247)
  // through the last org under (2024, 14) inclusive. The filter at a given
  // level is dropped for deeper levels once the cascade steps past that level's
  // bound, so e.g. END at the report_types level doesn't constrain orgs unless
  // we're also at that exact report_type.
  const START = (typeof window !== 'undefined' && window.OSPI_SCRAPER_START) || {};
  const END   = (typeof window !== 'undefined' && window.OSPI_SCRAPER_END)   || {};
  const LEVELS = ['years', 'report_types', 'orgs'];
  const matchesTarget = (opt, target) =>
    target !== undefined && (target === opt.value || target === opt.label);

  let combosProcessed = 0;

  async function descend(levelIdx, prefixParts, startPath, endPath) {
    if (levelIdx >= LEVELS.length) {
      await downloadDocuments(prefixParts.join(' - '));
      combosProcessed++;
      if (combosProcessed && combosProcessed % 25 === 0) {
        console.log(`Progress: ${combosProcessed} combinations processed.`);
      }
      return;
    }
    const boxId = LEVELS[levelIdx];
    const opts = realOptions(boxId);
    if (opts.length === 0) {
      await downloadDocuments(prefixParts.join(' - '));
      combosProcessed++;
      return;
    }

    const startTarget = startPath ? startPath[boxId] : undefined;
    const endTarget = endPath ? endPath[boxId] : undefined;
    let foundStart = startTarget === undefined;
    let skipped = 0;
    for (const o of opts) {
      if (!foundStart) {
        if (!matchesTarget(o, startTarget)) { skipped++; continue; }
        foundStart = true;
        if (skipped) console.log(`[resume] ${boxId}: skipped ${skipped} option(s), starting at ${o.label} (${o.value})`);
      }
      const matchedStart = matchesTarget(o, startTarget);
      const matchedEnd = matchesTarget(o, endTarget);
      console.group(`${boxId}: ${o.label} (${o.value})`);
      const setOk = setSelect(boxId, o.value);
      if (setOk) {
        await new Promise(r => setTimeout(r, POST_TRIGGER_PAUSE_MS));
        await waitForAjaxIdle();
        // Bounds stay in effect only on the exact matched path at this level.
        // Once we step past the matched option here, deeper levels iterate fully
        // for that bound.
        await descend(
          levelIdx + 1,
          [...prefixParts, o.label],
          matchedStart ? startPath : null,
          matchedEnd ? endPath : null,
        );
      }
      console.groupEnd();
      if (matchedEnd) {
        console.log(`[range] ${boxId}: reached end at ${o.label} (${o.value}); stopping further iteration at this level.`);
        break;
      }
    }
    if (!foundStart) {
      console.warn(`[resume] ${boxId}: start target ${JSON.stringify(startTarget)} not found among ${opts.length} option(s); skipping entire branch.`);
    }
  }

  try {
    if (Object.keys(START).length) console.log('Range start (inclusive):', START);
    if (Object.keys(END).length)   console.log('Range end (inclusive):',   END);
    await descend(
      0, [],
      Object.keys(START).length ? START : null,
      Object.keys(END).length ? END : null,
    );
    console.log(`Cascade complete after ${combosProcessed} combinations; waiting on ${pending.length} download(s) (${inflight} still inflight)...`);
    await Promise.allSettled(pending);
    console.log(`Done. ${combosProcessed} combinations processed, ${pending.length} downloads finished.`);
  } finally {
    $(document).off('ajaxSend.starsScraper ajaxComplete.starsScraper');
  }
})();
