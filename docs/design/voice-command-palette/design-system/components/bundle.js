window.Traceback = (function () {
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function wave() {
    var bars = "";
    for (var i = 0; i < 7; i++) bars += "<span></span>";
    return '<div class="tb-wave" aria-hidden="true">' + bars + "</div>";
  }

  var NAV = [
    { label: "Inbox", count: "6" },
    { label: "Tasks", count: "12" },
    { label: "Projects", count: "5" },
    { label: "Notes", count: "" },
    { label: "Folders", count: "" },
    { label: "Categories", count: "" },
    { label: "Archive", count: "" }
  ];

  function topbar(hintLabel) {
    return (
      '<div class="tb-topbar">' +
      '<div class="tb-topbar__brand">Traceback</div>' +
      '<div class="tb-topbar__hint">' + (hintLabel || 'Hold <kbd>&#8997; Option</kbd> + <kbd>Space</kbd> to speak') + "</div>" +
      "</div>"
    );
  }

  function sidebar(active) {
    var items = NAV.map(function (n) {
      var cls = "tb-nav-item" + (n.label === active ? " tb-nav-item--active" : "");
      return (
        '<div class="' + cls + '">' +
        "<span>" + n.label + "</span>" +
        (n.count ? '<span class="tb-count">' + n.count + "</span>" : "") +
        "</div>"
      );
    }).join("");
    return (
      '<div class="tb-sidebar">' +
      '<div class="tb-sidebar__group-label">Traceback</div>' +
      items +
      '<div class="tb-sidebar__group-label" style="margin-top:16px">Search</div>' +
      '<div class="tb-nav-item"><span>&#8997; Space to search by voice</span></div>' +
      "</div>"
    );
  }

  // ----- background content screens (what the app shows behind/under the panel) -----

  function bodyTasksOverdue(opts) {
    opts = opts || {};
    var rows = [
      ["Submit expense report", "3d late", true],
      ["Renew insurance", "1d late", true],
      ["Send vendor response", "1d late", true],
      ["Review Q3 budget draft", "Due today", false],
      ["Water office plants", "Due Fri", false]
    ];
    var trs = rows.map(function (r) {
      return (
        '<div class="tb-row' + (r[2] ? " tb-row--highlight" : "") + '">' +
        '<div class="tb-row__check"></div>' +
        '<div class="tb-row__title">' + esc(r[0]) + "</div>" +
        '<div class="tb-row__meta' + (r[2] ? " tb-row__meta--late" : "") + '">' + esc(r[1]) + "</div>" +
        "</div>"
      );
    }).join("");
    return (
      '<div class="tb-breadcrumb">Tasks</div>' +
      '<div class="tb-h1">All Tasks</div>' +
      '<div class="tb-table">' + trs + "</div>"
    );
  }

  function bodyProjects(opts) {
    opts = opts || {};
    var active = opts.opened || null;
    var rows = [
      ["DSA Learning", "18 notes &middot; 4 open tasks"],
      ["Kitchen Renovation", "6 notes &middot; 9 open tasks"],
      ["Course Notes", "31 notes &middot; 2 open tasks"],
      ["Home / Renovation", "2 notes &middot; 1 open task"],
      ["Archive / Renovation", "12 notes &middot; 0 open tasks"]
    ];
    var trs = rows.map(function (r) {
      var isActive = active && r[0] === active;
      return (
        '<div class="tb-row' + (isActive ? " tb-row--highlight" : "") + '">' +
        '<div class="tb-row__title">' + esc(r[0]) + "</div>" +
        '<div class="tb-row__meta">' + r[1] + "</div>" +
        "</div>"
      );
    }).join("");
    return (
      '<div class="tb-breadcrumb">' + (active ? "Projects / " + esc(active) : "Projects") + "</div>" +
      '<div class="tb-h1">' + (active ? esc(active) : "All Projects") + "</div>" +
      '<div class="tb-table">' + trs + "</div>"
    );
  }

  function bodyInbox() {
    var rows = [
      ["Voice command needs review", "&#8213; “add task follow up w...”", true],
      ["Voice command needs review", "&#8213; “remind me to call the...”", true],
      ["Unclassified note", "&#8213; pasted from clipboard", true],
      ["Unclassified note", "&#8213; “idea: weekend trip”", true],
      ["Unclassified note", "&#8213; meeting scratch notes", true],
      ["Failed recording", "&#8213; no speech detected", true]
    ];
    var trs = rows.map(function (r) {
      return (
        '<div class="tb-row">' +
        '<div class="tb-row__title">' + esc(r[0]) + "</div>" +
        '<div class="tb-row__meta">' + r[1] + "</div>" +
        "</div>"
      );
    }).join("");
    return '<div class="tb-breadcrumb">Inbox</div><div class="tb-h1">Inbox</div><div class="tb-table">' + trs + "</div>";
  }

  function shell(el, opts) {
    opts = opts || {};
    el.innerHTML =
      '<div class="tb-reset tb-frame">' +
      topbar(opts.hintLabel) +
      '<div class="tb-body">' +
      sidebar(opts.active || "Tasks") +
      '<div class="tb-content" id="tb-content-slot">' + (opts.bodyHtml || "") + "</div>" +
      "</div></div>";
    return el.querySelector("#tb-content-slot");
  }

  // ----- floating voice panel states -----

  function dock(innerHtml, panelClass) {
    return (
      '<div class="tb-panel-dock">' +
      '<div class="tb-panel ' + (panelClass || "") + '">' + innerHtml + "</div>" +
      "</div>"
    );
  }

  function panelRecording(seconds) {
    return dock(
      '<div class="tb-panel__row1">' +
        '<div class="tb-panel__status"><span class="tb-panel__dot tb-panel__dot--recording" aria-hidden="true"></span> Recording&hellip;</div>' +
        '<div class="tb-panel__time">0:0' + (seconds || 4) + "</div>" +
      "</div>" +
      wave() +
      '<div class="tb-panel__hints"><span>Release <kbd>&#8997; Option</kbd>+<kbd>Space</kbd> to send</span><span><kbd>Esc</kbd> to cancel</span></div>',
      "tb-panel--recording"
    );
  }

  function panelProcessing(query, note) {
    return dock(
      '<div class="tb-panel__query">' + esc(query) + "</div>" +
      '<div class="tb-panel__progress"><span class="tb-spinner" aria-hidden="true"></span>' + esc(note) + "</div>",
      "tb-panel--processing"
    );
  }

  function panelResult(opts) {
    var rows = opts.rows.map(function (r) {
      return (
        '<div class="tb-row">' +
        '<div class="tb-row__check"></div>' +
        '<div class="tb-row__title">' + esc(r[0]) + "</div>" +
        '<div class="tb-row__meta tb-row__meta--late">' + esc(r[1]) + "</div>" +
        "</div>"
      );
    }).join("");
    return dock(
      '<div class="tb-panel__head"><b>' + esc(opts.title) + '</b><span class="tb-panel__count">' + opts.count + "</span></div>" +
      '<div class="tb-plist">' + rows + "</div>" +
      '<div class="tb-panel__footer"><button class="tb-btn tb-btn--primary">' + esc(opts.primary || "Open Tasks") + '</button><button class="tb-btn tb-btn--ghost">Dismiss</button></div>',
      "tb-panel--result"
    );
  }

  function panelMultiple(opts) {
    var rows = opts.rows.map(function (r, i) {
      return (
        '<div class="tb-prow">' +
        '<div class="tb-prow__idx">' + (i + 1) + "</div>" +
        '<div class="tb-prow__bullet"></div>' +
        '<div class="tb-prow__main"><div class="tb-prow__title">' + esc(r[0]) + '</div><div class="tb-prow__path">' + esc(r[1]) + "</div></div>" +
        "</div>"
      );
    }).join("");
    return dock(
      '<div class="tb-panel__head"><b>' + esc(opts.title) + '</b><span class="tb-panel__count">' + opts.count + "</span></div>" +
      '<div class="tb-plist">' + rows + "</div>" +
      '<div class="tb-panel__note">Say &ldquo;' + esc(opts.hint || "open the first one") + '&rdquo; or select one</div>',
      "tb-panel--result"
    );
  }

  function panelAmbiguity(opts) {
    var rows = opts.rows.map(function (r, i) {
      return (
        '<div class="tb-prow">' +
        '<div class="tb-prow__idx">' + (i + 1) + "</div>" +
        '<div class="tb-prow__bullet"></div>' +
        '<div class="tb-prow__main"><div class="tb-prow__title">' + esc(r[0]) + '</div><div class="tb-prow__path">' + esc(r[1]) + "</div></div>" +
        "</div>"
      );
    }).join("");
    return dock(
      '<div class="tb-panel__query" style="margin-bottom:10px">' + esc(opts.query) + "</div>" +
      '<div class="tb-panel__head"><b>' + esc(opts.title) + "</b></div>" +
      '<div class="tb-plist">' + rows + "</div>" +
      '<div class="tb-panel__note">Say &ldquo;the first one&rdquo; or select it &mdash; Traceback never guesses.</div>',
      "tb-panel--result"
    );
  }

  function panelConfirm(text) {
    return dock('<div class="tb-panel__confirm"><span class="tb-check">&#10003;</span> ' + text + "</div>", "tb-panel--result");
  }

  function panelUnavailable(opts) {
    return dock(
      '<div class="tb-panel__status" style="margin-bottom:6px"><span class="tb-panel__error-icon">&#9888;</span> <span class="tb-panel__error-title">' + esc(opts.title) + "</span></div>" +
      '<div class="tb-panel__note" style="margin-top:0">' + esc(opts.detail) + "</div>" +
      '<div class="tb-panel__footer"><button class="tb-btn tb-btn--ghost">Dismiss</button></div>',
      ""
    );
  }

  function panelCancelled() {
    return dock('<div class="tb-panel__note" style="margin:0">Cancelled &mdash; nothing was sent.</div>', "");
  }

  function panelIdle() {
    return dock(
      '<div class="tb-panel__hints" style="justify-content:flex-start; gap:8px;"><span style="width:9px;height:9px;border-radius:50%;border:1.5px solid var(--color-ink-muted);display:inline-block;"></span> Hold <kbd>&#8997; Option</kbd>+<kbd>Space</kbd> to speak</div>',
      "tb-panel--idle"
    );
  }

  function panelNoResults(query) {
    return dock(
      '<div class="tb-panel__query">' + esc(query) + "</div>" +
      '<div class="tb-panel__note" style="margin-top:2px">No matches found. Try rephrasing, or say &ldquo;show all tasks&rdquo;.</div>',
      ""
    );
  }

  function panelPermission() {
    return dock(
      '<div class="tb-panel__status" style="margin-bottom:6px"><span class="tb-panel__error-icon">&#9888;</span> <span class="tb-panel__error-title">Microphone access needed</span></div>' +
      '<div class="tb-panel__note" style="margin-top:0">Traceback can&rsquo;t hear you. Grant microphone access in System Settings &rarr; Privacy &amp; Security.</div>' +
      '<div class="tb-panel__footer"><button class="tb-btn tb-btn--primary">Open Settings</button><button class="tb-btn tb-btn--ghost">Dismiss</button></div>',
      ""
    );
  }

  // ----- macOS notification + desktop scene -----

  function notification(opts) {
    return (
      '<div class="tb-notification">' +
      '<div class="tb-notification__head"><span class="tb-notification__badge">T</span><span class="tb-notification__app">TRACEBACK</span><span class="tb-notification__time">now</span></div>' +
      '<div class="tb-notification__title">' + esc(opts.title) + "</div>" +
      '<div class="tb-notification__body">' + esc(opts.body) + "</div>" +
      (opts.action ? '<div class="tb-notification__action">' + esc(opts.action) + "</div>" : "") +
      "</div>"
    );
  }

  function desktopScene(el, opts) {
    el.innerHTML =
      '<div class="tb-reset tb-desktop">' +
      '<div class="tb-menubar"><span>&#63743; Mail</span><span>Tue 9:41 AM</span></div>' +
      '<div class="tb-window">' +
      '<div class="tb-window__bar"><span class="tb-window__dot"></span><span class="tb-window__dot"></span><span class="tb-window__dot"></span><span class="tb-window__title">Mail &mdash; Inbox</span></div>' +
      '<div class="tb-window__body">Traceback is running in the background. The &#8997; Option + Space shortcut still works from any app &mdash; Traceback stays out of the way instead of stealing focus.</div>' +
      "</div>" +
      (opts.notificationHtml || "") +
      "</div>";
  }

  return {
    shell: shell,
    bodyTasksOverdue: bodyTasksOverdue,
    bodyProjects: bodyProjects,
    bodyInbox: bodyInbox,
    panelRecording: panelRecording,
    panelProcessing: panelProcessing,
    panelResult: panelResult,
    panelMultiple: panelMultiple,
    panelAmbiguity: panelAmbiguity,
    panelConfirm: panelConfirm,
    panelUnavailable: panelUnavailable,
    panelCancelled: panelCancelled,
    panelIdle: panelIdle,
    panelNoResults: panelNoResults,
    panelPermission: panelPermission,
    notification: notification,
    desktopScene: desktopScene
  };
})();
