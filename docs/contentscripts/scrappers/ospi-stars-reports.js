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
  const DOWNLOAD_GAP_MIN_MS = 500;   // jittered gap between downloads
  const DOWNLOAD_GAP_MAX_MS = 5000;

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
  // Track inflight count and wait until it stays at 0 for AJAX_QUIET_MS.
  let inflight = 0;
  const onSend = () => { inflight++; };
  const onComplete = () => { inflight--; };
  $(document).on('ajaxSend.starsScraper', onSend);
  $(document).on('ajaxComplete.starsScraper', onComplete);

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
        console.error(`[fail] ${url} (${prefix})`, err);
      }
      const gap = jitteredGap();
      console.log(`[wait] ${Math.round(gap)}ms`);
      await new Promise(r => setTimeout(r, gap));
    }
  }

  try {
    const years = realOptions('years');
    console.log(`Found ${years.length} year(s). Report types and orgs vary per year.`);

    let combosProcessed = 0;
    for (const y of years) {
      console.group(`year=${y.label} (${y.value})`);
      // Changing year refetches both report_types and orgs.
      setSelect('years', y.value);
      await new Promise(r => setTimeout(r, POST_TRIGGER_PAUSE_MS));
      await waitForAjaxIdle();

      const reportTypes = realOptions('report_types');
      console.log(`  ${reportTypes.length} report type(s) for this year`);

      for (const r of reportTypes) {
        console.group(`report=${r.label} (${r.value})`);
        // Changing report_type refetches orgs.
        if (!setSelect('report_types', r.value)) { console.groupEnd(); continue; }
        await new Promise(rr => setTimeout(rr, POST_TRIGGER_PAUSE_MS));
        await waitForAjaxIdle();

        const orgs = realOptions('orgs');
        console.log(`    ${orgs.length} org(s) for this combination`);

        if (orgs.length === 0) {
          await downloadDocuments(`${y.label} - ${r.label}`);
          combosProcessed++;
        } else {
          for (const o of orgs) {
            if (!setSelect('orgs', o.value)) continue;
            await new Promise(rr => setTimeout(rr, POST_TRIGGER_PAUSE_MS));
            await waitForAjaxIdle();
            await downloadDocuments(`${y.label} - ${r.label} - ${o.label}`);
            combosProcessed++;
            if (combosProcessed % 25 === 0) {
              console.log(`Progress: ${combosProcessed} combinations processed.`);
            }
          }
        }
        console.groupEnd();
      }
      console.groupEnd();
    }
    console.log(`Done. ${combosProcessed} combinations processed.`);
  } finally {
    $(document).off('ajaxSend.starsScraper ajaxComplete.starsScraper');
  }
})();
