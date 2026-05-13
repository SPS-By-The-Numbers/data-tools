// OSPI STARS page diagnostic.
//
// Run from the JS console on the STARS reports page. Inspects the year /
// report_type / org controls and reports what's actually in the live DOM
// (post-JS), so we can figure out why dispatching change on the native select
// isn't triggering AJAX.

(() => {
  const ids = ['years', 'report_types', 'orgs', 'documents'];
  const out = { jquery: null, controls: {} };

  out.jquery = window.jQuery
    ? { present: true, version: window.jQuery.fn && window.jQuery.fn.jquery }
    : { present: false };

  for (const id of ids) {
    const container = document.getElementById(id);
    if (!container) {
      out.controls[id] = { found: false };
      continue;
    }
    const sel = container.querySelector('select');
    const childTags = [...container.children].map(c => `${c.tagName.toLowerCase()}${c.className ? '.' + c.className.replace(/\s+/g, '.') : ''}`);
    const containerStyle = getComputedStyle(container);
    const selStyle = sel ? getComputedStyle(sel) : null;
    out.controls[id] = {
      found: true,
      containerTag: container.tagName,
      containerClass: container.className,
      containerVisible: containerStyle.display !== 'none' && containerStyle.visibility !== 'hidden',
      containerSize: { w: container.offsetWidth, h: container.offsetHeight },
      childTags,
      selectFound: !!sel,
      selectValue: sel ? sel.value : null,
      selectVisible: selStyle ? (selStyle.display !== 'none' && selStyle.visibility !== 'hidden') : null,
      selectSize: sel ? { w: sel.offsetWidth, h: sel.offsetHeight } : null,
      optionCount: sel ? sel.options.length : 0,
      dataOnce: container.getAttribute('data-once'),
      outerHTMLHead: container.outerHTML.slice(0, 600),
    };
  }

  // Walk up #years to find anything that smells like a custom-select wrapper
  // (Choices.js, Select2, Tom Select, bootstrap-select, jQuery UI selectmenu).
  const widgetSignatures = [
    'choices', 'choices__inner',           // Choices.js
    'select2', 'select2-container',         // Select2
    'ts-wrapper', 'ts-control',             // Tom Select
    'bootstrap-select',                     // bootstrap-select
    'ui-selectmenu-button',                 // jQuery UI selectmenu
    'selectric',                            // Selectric
    'nice-select', 'sumoselect',
    'dropdown-menu', 'dropdown-toggle',     // generic Bootstrap dropdown
  ];
  out.widgetHits = [];
  for (const sig of widgetSignatures) {
    const els = document.getElementsByClassName(sig);
    if (els.length) {
      out.widgetHits.push({ class: sig, count: els.length, firstOuter: els[0].outerHTML.slice(0, 200) });
    }
  }

  // Look for scripts/links that hint at the AJAX endpoint or widget library.
  out.scriptSrcs = [...document.scripts].map(s => s.src).filter(s => s).slice(0, 40);

  // Pull all event listener names if available via getEventListeners (Chrome
  // DevTools-only). We can't call it from a script normally; just log a hint.
  out.note = 'In DevTools, also run: getEventListeners(document.querySelector("#years select")) and same for #report_types/#orgs.';

  console.log('=== OSPI STARS diag ===');
  console.log(JSON.stringify(out, null, 2));
  console.log('=== end diag ===');
  return out;
})();
