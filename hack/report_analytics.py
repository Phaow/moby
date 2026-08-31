#!/usr/bin/env python3
"""
Analyze gotestsum JSON report and generate an interactive HTML dashboard.
"""
import json, sys, os
from pathlib import Path
from collections import defaultdict

CK_PASS = "&#10003;"
CK_FAIL = "&#10007;"
CK_SKIP = "&#8856;"

SUITE_ICONS = {
    "TestDockerAPISuite": "&#9881;",
    "TestDockerCLIRunSuite": "&#9654;",
    "TestDockerCLICreateSuite": "&#10010;",
    "TestDockerCLIStartSuite": "&#9650;",
    "TestDockerCLIInspectSuite": "&#128269;",
    "TestDockerCLIPsSuite": "&#128203;",
    "TestDockerCLILogsSuite": "&#128203;",
    "TestDockerCLIExecSuite": "&#9654;",
    "TestDockerCLIAttachSuite": "&#128279;",
    "TestDockerCLIImagesSuite": "&#128247;",
    "TestDockerCLINetworkSuite": "&#127760;",
    "TestDockerCLIVolumeSuite": "&#128190;",
    "TestDockerCLICpSuite": "&#128462;",
    "TestDockerCLIRestartSuite": "&#8635;",
    "TestDockerCLIRmiSuite": "&#128465;",
}


def parse_report(path):
    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return events


def classify_events(events):
    parent_names = set()
    for e in events:
        test = e.get("Test", "")
        if "/" in test:
            parent_names.add(test.rsplit("/", 1)[0])

    parent_to_top = {}
    for parent in parent_names:
        if "/" in parent:
            seg0 = parent.split("/")[0]
            parent_to_top[parent] = seg0 if seg0.endswith("Suite") else parent
        else:
            if parent.endswith("Suite"):
                parent_to_top[parent] = parent
            else:
                found = False
                for p in parent_names:
                    if p.startswith(parent + "/"):
                        parent_to_top[parent] = parent_to_top.get(p, parent)
                        found = True
                        break
                if not found:
                    parent_to_top[parent] = parent

    def suite_of(test_name):
        if "/" in test_name:
            seg0 = test_name.split("/")[0]
            return seg0 if seg0.endswith("Suite") else parent_to_top.get(test_name.rsplit("/", 1)[0], test_name.rsplit("/", 1)[0])
        else:
            return parent_to_top.get(test_name, test_name)

    cases = {}
    suites = {}
    for e in events:
        action = e.get("Action", "")
        test = e.get("Test", "")
        elapsed = e.get("Elapsed", 0)
        output = e.get("Output", "")
        is_sub = "/" in test
        sn = suite_of(test)
        if is_sub:
            if test not in cases:
                cases[test] = {"actions": [], "outputs": [], "elapsed": 0, "action": None}
            c = cases[test]
            c["actions"].append(action)
            if output:
                c["outputs"].append(output)
            if action in ("pass", "fail", "skip"):
                c["action"] = action
                c["elapsed"] = elapsed
        else:
            if sn not in suites:
                suites[sn] = {"pass": 0, "fail": 0, "skip": 0, "elapsed": 0}
            if action in ("pass", "fail", "skip"):
                suites[sn][action] += 1
                suites[sn]["elapsed"] = elapsed

    suite_cases = defaultdict(list)
    for case, info in cases.items():
        sn = suite_of(case)
        suite_cases[sn].append({
            "name": case,
            "action": info["action"],
            "elapsed": info["elapsed"],
            "outputs": info["outputs"],
        })
    return cases, suites, suite_cases


def extract_meta(events):
    # `docker version` output is dumped at package level; track which section
    # (Client / Server / containerd / runc / docker-init) each line belongs to
    # so we pick the Engine's versions instead of docker-init's.
    meta = {"client": {}, "server": {}, "sub": {}}
    section = None
    sub_name = None
    start_time, end_time = None, None
    for e in events:
        action = e.get("Action", "")
        out = e.get("Output", "")
        if action == "output" and not e.get("Test"):
            stripped = out.lstrip()
            if stripped.startswith("Client:"):
                section = "client"
            elif stripped.startswith("Server:"):
                section = "server"
            elif stripped.startswith(("containerd:", "runc:", "docker-init:")):
                section = "sub"
                sub_name = stripped.split(":", 1)[0].strip()
            elif section == "sub":
                if sub_name and "Version:" in out:
                    meta["sub"].setdefault(sub_name, out.split("Version:")[-1].strip())
            elif section in ("client", "server"):
                if "Version:" in out:
                    meta[section]["ver"] = out.split("Version:")[-1].strip()
                elif "API version:" in out:
                    meta[section]["api"] = out.split("API version:")[-1].strip().split()[0]
                elif "Go version:" in out:
                    meta[section]["go_ver"] = out.split("Go version:")[-1].strip()
                elif "Git commit:" in out:
                    meta[section]["commit"] = out.split("Git commit:")[-1].strip()
        if action == "start" and e.get("Package") == "github.com/docker/docker/integration-cli":
            if start_time is None:
                start_time = e.get("Time", "")
        if action == "fail" and not e.get("Test") and e.get("Package") == "github.com/docker/docker/integration-cli":
            end_time = e.get("Time", "")
    # Prefer the daemon (Server) versions, fall back to client
    ver = meta["server"].get("ver") or meta["client"].get("ver") or "?"
    api = meta["server"].get("api") or meta["client"].get("api") or "?"
    commit = meta["server"].get("commit") or meta["client"].get("commit") or "?"
    go_ver = meta["server"].get("go_ver") or meta["client"].get("go_ver") or "?"
    return ver, api, commit, go_ver, meta["sub"], start_time, end_time


def stat_counts(cases):
    total = len(cases)
    passed = sum(1 for v in cases.values() if v["action"] == "pass")
    failed = sum(1 for v in cases.values() if v["action"] == "fail")
    skipped = sum(1 for v in cases.values() if v["action"] == "skip")
    unknown = total - passed - failed - skipped
    return total, passed, failed, skipped, unknown


def pass_rate_str(p, f, s):
    t = p + f + s
    return "0%" if t == 0 else f"{100.0 * p / t:.1f}%"


def fmt_elapsed(s):
    if s <= 0:
        return "-"
    if s < 1:
        return f"{s:.2f}s"
    m, sec = int(s // 60), int(s % 60)
    return f"{m}m {sec}s" if m else f"{sec}s"


def failure_snippet(outputs):
    priority_kw = [
        "assertion", "Error:", "Failures:", "ExitCode",
        "Expected", "Stdout", "Stderr", "Command:", "docker:",
        "Error response", "unable", "failed",
    ]
    lines, seen = [], set()
    for out in reversed(outputs):
        for ln in reversed(out.split("\n")):
            ln = ln.strip()
            if not ln or ln in seen:
                continue
            if any(kw.lower() in ln.lower() for kw in priority_kw):
                seen.add(ln)
                lines.append(ln)
    return list(dict.fromkeys(reversed(lines)))[:5]


def escape_html(s):
    if not isinstance(s, str):
        return s
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;").replace("'", "&#39;"))


def build_html(data):
    # ── CSS ────────────────────────────────────────────────────────────────────
    css = """
* { box-sizing:border-box; margin:0; padding:0; }
body { background:#0d1117; color:#e6edf3; font-family:system-ui,sans-serif; font-size:14px; }
a { color:#58a6ff; text-decoration:none; }

header { background:#161b22; border-bottom:1px solid #30363d; padding:14px 24px; }
.header-title { font-size:17px; font-weight:700; margin-bottom:3px; }
.header-meta { font-size:12px; color:#8b949e; }
.header-meta span { margin-right:18px; }
.v { color:#58a6ff; font-family:monospace; }

.stats { display:flex; gap:10px; padding:14px 24px; flex-wrap:wrap; }
.sc { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:10px 18px; min-width:105px; cursor:pointer; transition:border-color .15s; }
.sc:hover { border-color:#58a6ff; }
.lbl { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:.04em; margin-bottom:2px; }
.val { font-size:22px; font-weight:700; }
.val.g { color:#3fb950; } .val.r { color:#f85149; }
.val.y { color:#d29922; } .val.u { color:#848d97; } .val.b { color:#58a6ff; }

.bar-row { padding:6px 24px 14px; }
.bar-lbl { font-size:11px; color:#8b949e; margin-bottom:5px; text-transform:uppercase; }
.bar { height:9px; border-radius:4px; background:#30363d; display:flex; overflow:hidden; }
.bi { height:100%; }
.bi.g { background:#3fb950; } .bi.r { background:#f85149; } .bi.y { background:#d29922; }

.filters { display:flex; gap:8px; padding:8px 24px; align-items:center; flex-wrap:wrap; background:#161b22; border-bottom:1px solid #30363d; }
.filters label { font-size:12px; color:#8b949e; }
.filters select, .filters input { background:#1f2937; border:1px solid #30363d; color:#e6edf3; border-radius:4px; padding:4px 8px; font-size:13px; }
.filters input[type=text] { width:200px; }
.filters input[type=checkbox] { width:auto; }
.fcnt { font-size:12px; color:#8b949e; margin-left:auto; }

.suite-list { padding:0 24px 24px; }

.suite { background:#161b22; border:1px solid #30363d; border-radius:8px; margin:10px 0; overflow:hidden; }
.suite-hdr { display:flex; align-items:center; gap:10px; padding:9px 14px; cursor:pointer; user-select:none; border-bottom:1px solid transparent; }
.suite-hdr:hover { background:#1f2937; }
.suite-hdr.open { border-bottom-color:#30363d; }
.tog { color:#8b949e; font-size:12px; width:16px; flex-shrink:0; }
.suite-icon { font-size:15px; width:20px; text-align:center; flex-shrink:0; }
.sname { font-weight:600; font-size:14px; flex:1; }
.badge { font-size:11px; padding:2px 7px; border-radius:999px; font-weight:600; margin-right:2px; }
.bg { background:rgba(63,185,80,.12); color:#3fb950; }
.br { background:rgba(248,81,73,.12); color:#f85149; }
.by { background:rgba(210,153,34,.12); color:#d29922; }
.rate { font-size:12px; color:#8b949e; min-width:45px; text-align:right; margin-right:8px; }
.elt { font-size:11px; color:#8b949e; min-width:55px; text-align:right; font-family:monospace; }

.cases { display:none; }
.cases.open { display:block; }

.case { display:flex; align-items:flex-start; gap:10px; padding:7px 14px; border-bottom:1px solid #30363d; font-size:13px; }
.case:last-child { border-bottom:none; }
.case:hover { background:rgba(255,255,255,.02); }

.dot { width:12px; height:12px; border-radius:50%; margin-top:3px; flex-shrink:0; }
.dot.g { background:#3fb950; } .dot.r { background:#f85149; }
.dot.y { background:#d29922; } .dot.u { background:#848d97; }

.cname { flex:1; font-family:monospace; font-size:12px; word-break:break-all; }
.celt { font-size:11px; color:#8b949e; font-family:monospace; min-width:50px; text-align:right; }
.cdet-btn { font-size:11px; color:#58a6ff; cursor:pointer; white-space:nowrap; flex-shrink:0; }
.cdet { display:none; padding:6px 14px 10px 36px; background:rgba(0,0,0,.18); }
.cdet.open { display:block; }
.cdet pre { background:#090d12; border:1px solid #30363d; border-radius:4px; padding:8px 10px; font-size:11px; font-family:monospace; white-space:pre-wrap; word-break:break-all; color:#c9d1d9; max-height:250px; overflow-y:auto; line-height:1.6; }
.cdet .lbl { font-size:11px; color:#8b949e; margin-bottom:3px; text-transform:uppercase; }
.fline { color:#f85149; } .pline { color:#3fb950; }

.suite-footer { padding:6px 14px; background:rgba(0,0,0,.1); font-size:11px; color:#8b949e; border-top:1px solid #30363d; }
"""

    # ── JS ─────────────────────────────────────────────────────────────────────
    js = r"""
var DATA;
var CK_PASS = '✓';
var CK_FAIL = '✗';
var CK_SKIP = '○';

function updateSuiteOptions(statusVal, preserveCur) {
  var suiteSel = document.getElementById('f-suite');
  var curVal = suiteSel.value;
  suiteSel.innerHTML = '<option value="all">All suites<\/option>';
  DATA.suites.forEach(function(s) {
    var hasMatch = statusVal === 'all' || s.cases.some(function(c) {
      if (statusVal === 'fail') return c.action === 'fail';
      if (statusVal === 'pass') return c.action === 'pass';
      if (statusVal === 'skip') return c.action === 'skip';
      if (statusVal === 'f+s') return c.action === 'fail' || c.action === 'skip';
      return false;
    });
    if (hasMatch) {
      suiteSel.innerHTML += '<option value="' + s.name + '">' + s.name + '<\/option>';
    }
  });
  if (preserveCur) {
    var found = false;
    for (var i = 0; i < suiteSel.options.length; i++) {
      if (suiteSel.options[i].value === curVal) { found = true; break; }
    }
    suiteSel.value = found ? curVal : 'all';
  } else {
    suiteSel.value = 'all';
  }
}

function applyFilters() {
  var status = document.getElementById('f-status').value;
  var suite = document.getElementById('f-suite').value;
  var search = document.getElementById('f-search').value.toLowerCase();
  var hidePass = document.getElementById('f-hide-pass').checked;
  var filterActive = status !== 'all' || suite !== 'all' || search !== '' || hidePass;
  var visible = 0;

  document.querySelectorAll('.suite').forEach(function(block) {
    var sName = block.dataset.suite;
    var sVisible = false;
    // NOTE: scope the query to the block — document.querySelectorAll() ignores
    // a second argument, so '.case' would match every case in the document.
    block.querySelectorAll('.case').forEach(function(row) {
      var action = row.dataset.action || 'unknown';
      var nameEl = row.querySelector('.cname');
      var name = nameEl ? nameEl.textContent.toLowerCase() : '';
      var show = true;
      if (status === 'fail' && action !== 'fail') show = false;
      if (status === 'skip' && action !== 'skip') show = false;
      if (status === 'pass' && action !== 'pass') show = false;
      if (status === 'f+s' && action !== 'fail' && action !== 'skip') show = false;
      if (suite !== 'all' && sName !== suite) show = false;
      if (search && name.indexOf(search) === -1) show = false;
      if (hidePass && action === 'pass') show = false;
      row.style.display = show ? '' : 'none';
      if (show) { visible++; sVisible = true; }
    });
    block.style.display = sVisible ? '' : 'none';
    if (!sVisible) {
      if (block._casesDiv) block._casesDiv.classList.remove('open');
      if (block._hdr) block._hdr.classList.remove('open');
      if (block._tog) block._tog.textContent = '▶';
    } else if (filterActive) {
      if (block._casesDiv) block._casesDiv.classList.add('open');
      if (block._hdr) block._hdr.classList.add('open');
      if (block._tog) block._tog.textContent = '▼';
    }
  });

  document.getElementById('fcnt').textContent = 'Showing ' + visible + ' / ' + window._totalCases + ' cases';

  // Auto-expand failure details when filtering for failures
  if (status === 'fail' || status === 'f+s') {
    document.querySelectorAll('.case').forEach(function(row) {
      if (row.dataset.action !== 'fail') return;
      if (row.style.display === 'none') return;
      var suiteBlock = row.closest('.suite');
      if (suiteBlock && suiteBlock.style.display === 'none') return;
      var det = row.querySelector('.cdet');
      var btn = row.querySelector('.cdet-btn');
      if (det && !det.classList.contains('open')) {
        det.classList.add('open');
        if (btn) btn.textContent = 'hide ▲';
      }
    });
  }
}

document.getElementById('f-suite').addEventListener('change', applyFilters);
document.getElementById('f-status').addEventListener('change', function() {
  updateSuiteOptions(this.value, false);
  applyFilters();
});
document.getElementById('f-search').addEventListener('input', applyFilters);
document.getElementById('f-hide-pass').addEventListener('change', applyFilters);

document.querySelectorAll('.sc[data-action]').forEach(function(el) {
  el.addEventListener('click', function() {
    document.getElementById('f-status').value = el.dataset.action;
    updateSuiteOptions(el.dataset.action, true);
    applyFilters();
  });
});

document.querySelectorAll('.cdet-btn').forEach(function(btn) {
  btn.addEventListener('click', function() {
    var det = document.getElementById(this.dataset.id);
    if (!det) return;
    var open = det.classList.toggle('open');
    this.textContent = open ? 'hide ▲' : 'details ▼';
  });
});
"""

    # ── Assemble ────────────────────────────────────────────────────────────────
    s = data["stats"]

    # Stat cards
    stat_defs = [
        {"label": "Total",   "val": s["total"],   "cls": "b", "action": ""},
        {"label": "Passed",  "val": s["passed"],  "cls": "g", "action": "pass"},
        {"label": "Failed",  "val": s["failed"],   "cls": "r", "action": "fail"},
        {"label": "Skipped", "val": s["skipped"], "cls": "y", "action": "skip"},
        {"label": "Unknown", "val": s["unknown"],  "cls": "u", "action": ""},
        {"label": "Rate",    "val": data["meta"]["rate"], "cls": s["rate_cls"], "action": ""},
    ]
    stats_html = "".join(
        '<div class="sc"' + (' data-action="' + d["action"] + '"' if d["action"] else '') + '>' +
        '<div class="lbl">' + d["label"] + '</div><div class="val ' + d["cls"] + '">' + str(d["val"]) + '</div></div>'
        for d in stat_defs
    )

    tp = s["passed"] + s["failed"] + s["skipped"] or 1
    bar_html = (
        '<div class="bar-lbl">Result distribution — ' + data["meta"]["rate"] + ' pass rate</div>' +
        '<div class="bar">' +
        '<div class="bi g" style="width:' + str(round(100 * s["passed"] / tp, 2)) + '%"></div>' +
        '<div class="bi r" style="width:' + str(round(100 * s["failed"] / tp, 2)) + '%"></div>' +
        '<div class="bi y" style="width:' + str(round(100 * s["skipped"] / tp, 2)) + '%"></div>' +
        '</div>'
    )

    # Suite blocks
    suite_blocks = []
    for suite in data["suites"]:
        cases_html = ""
        for ci, c in enumerate(suite["cases"]):
            dot_cls = {"pass": "g", "fail": "r", "skip": "y"}.get(c["action"], "u")
            det_id = "cdet-" + str(suite["_idx"]) + "-" + str(ci)
            fail_lines = "".join(
                '<div class="fline">' + escape_html(ln) + '</div>'
                for ln in (c.get("failLines") or [])
            ) or '<span style="color:#8b949e">No output captured.</span>'
            cases_html += (
                '<div class="case" data-action="' + str(c["action"]) + '">' +
                '<div class="dot ' + dot_cls + '"></div>' +
                '<span class="cname">' + escape_html(c["name"]) + '</span>' +
                '<span class="celt">' + c["elapsed"] + '</span>' +
                '<span class="cdet-btn" data-id="' + det_id + '">details &#9660;</span>' +
                '<div class="cdet" id="' + det_id + '">' +
                '<div class="lbl">' + ("Failure output" if c["action"] == "fail" else "Output") + '</div>' +
                '<pre>' + fail_lines + '</pre>' +
                '</div>' +
                '</div>'
            )
        icon = SUITE_ICONS.get(suite["name"], "&#9654;")
        is_open = suite["fail"] > 0
        block = (
            '<div class="suite" data-suite="' + escape_html(suite["name"]) + '">' +
            '<div class="suite-hdr' + (" open" if is_open else "") + '">' +
            '<span class="tog">' + ("&#9660;" if is_open else "&#9654;") + '</span>' +
            '<span class="suite-icon">' + icon + '</span>' +
            '<span class="sname">' + escape_html(suite["name"]) + '</span>' +
            '<span class="badge bg">' + str(suite["pass"]) + ' ' + CK_PASS + '</span>' +
            '<span class="badge br">' + str(suite["fail"]) + ' ' + CK_FAIL + '</span>' +
            '<span class="badge by">' + str(suite["skip"]) + ' ' + CK_SKIP + '</span>' +
            '<span class="rate">' + suite["rate"] + '</span>' +
            '<span class="elt">' + suite["elapsed"] + '</span>' +
            '</div>' +
            '<div class="cases' + (" open" if is_open else "") + '">' +
            cases_html +
            '</div>' +
            '<div class="suite-footer">' + str(len(suite["cases"])) + ' cases &middot; elapsed ' + suite["elapsed"] + '</div>' +
            '</div>'
        )
        suite_blocks.append(block)

    suite_list_html = "".join(suite_blocks)

    # Data JSON (embed into page)
    data_json = json.dumps(data, ensure_ascii=False)

    # Build init JS — all DOM content is already in HTML, just wire up events
    init_js = (
        'DATA = ' + data_json + ';'
        'window._totalCases = ' + str(data["stats"]["total"]) + ';'
        'updateSuiteOptions("all", false);'
        'document.querySelectorAll(".suite").forEach(function(block) {'
            'block._hdr = block.querySelector(".suite-hdr");'
            'block._casesDiv = block.querySelector(".cases");'
            'block._tog = block._hdr ? block._hdr.querySelector(".tog") : null;'
            'if (!block._hdr || !block._casesDiv) return;'
            'block._hdr.addEventListener("click", function() {'
                'var open = block._casesDiv.classList.toggle("open");'
                'block._hdr.classList.toggle("open", open);'
                'if (block._tog) block._tog.innerHTML = open ? "&#9660;" : "&#9654;";'
            '});'
        '});'
        'applyFilters();'
    )
    init_js_escaped = init_js.replace("</script>", "<" + "/script>")

    full_html = (
        '<!DOCTYPE html>\n'
        '<html lang="en">\n'
        '<head>\n'
        '<meta charset="UTF-8">\n'
        '<meta name="viewport" content="width=device-width,initial-scale=1">\n'
        '<title>Test Report</title>\n'
        '<style>\n' + css + '</style>\n'
        '</head>\n'
        '<body>\n'
        '<header>\n'
        '  <div class="header-title" id="report-title">Test Report: ' + escape_html(data["meta"]["_title"]) + '</div>\n'
        '  <div class="header-meta">\n'
        '    <span>Docker <span class="v" id="dv">' + escape_html(data["meta"]["ver"]) + '</span></span>\n'
        '    <span>API <span class="v" id="da">' + escape_html(data["meta"]["api"]) + '</span></span>\n'
        '    <span>Go <span class="v" id="gv">' + escape_html(data["meta"]["go_ver"]) + '</span></span>\n'
        '    <span>Commit <span class="v" id="dc">' + escape_html(data["meta"]["commit"][:12]) + '</span></span>\n'
        + ''.join(
            '    <span>' + escape_html(name) + ' <span class="v">' + escape_html(sub_ver) + '</span></span>\n'
            for name, sub_ver in data["meta"]["sub_versions"].items()
        ) +
        '  </div>\n'
        '</header>\n'
        '<div class="stats" id="stats">' + stats_html + '</div>\n'
        '<div class="bar-row" id="bar-row">' + bar_html + '</div>\n'
        '<div class="filters">\n'
        '  <label>Status:</label>\n'
        '  <select id="f-status"><option value="all">All</option><option value="fail">Failed only</option><option value="skip">Skipped only</option><option value="pass">Passed only</option><option value="f+s">Failed + Skipped</option></select>\n'
        '  <label>Suite:</label>\n'
        '  <select id="f-suite"><option value="all">All suites</option></select>\n'
        '  <label>Search:</label>\n'
        '  <input type="text" id="f-search" placeholder="Filter by test name...">\n'
        '  <label style="cursor:pointer"><input type="checkbox" id="f-hide-pass"> Hide passed</label>\n'
        '  <span class="fcnt" id="fcnt"></span>\n'
        '</div>\n'
        '<div class="suite-list" id="suite-list">\n'
        + suite_list_html + '\n'
        '</div>\n'
        '<script>\n' + js + '\n' + init_js_escaped + '\n</script>\n'
        '</body>\n'
        '</html>\n'
    )
    return full_html


# ── Main ──────────────────────────────────────────────────────────────────────
if len(sys.argv) < 2:
    print(f"Usage: {sys.argv[0]} <report.json> [output.html]")
    sys.exit(1)

json_path = Path(sys.argv[1])
output_path = Path(sys.argv[2]) if len(sys.argv) > 2 else json_path.with_suffix(".html")

if not json_path.exists():
    print(f"ERROR: {json_path} not found")
    sys.exit(1)

events = parse_report(json_path)
cases, suites, suite_cases = classify_events(events)
total, passed, failed, skipped, unknown = stat_counts(cases)
ver, api, commit, go_ver, sub_versions, start_time, end_time = extract_meta(events)
rate = pass_rate_str(passed, failed, skipped)

def pri(a):
    return {"fail": 0, "skip": 1, "pass": 2, None: 3}.get(a, 4)

suite_data = []
for suite_name in sorted(suite_cases.keys()):
    s_cases = suite_cases[suite_name]
    s_pass = sum(1 for c in s_cases if c["action"] == "pass")
    s_fail = sum(1 for c in s_cases if c["action"] == "fail")
    s_skip = sum(1 for c in s_cases if c["action"] == "skip")
    s_elapsed = suites.get(suite_name, {}).get("elapsed", 0)
    sorted_cases = sorted(s_cases, key=lambda c: (pri(c["action"]), c["name"]))
    suite_data.append({
        "name": suite_name,
        "pass": s_pass,
        "fail": s_fail,
        "skip": s_skip,
        "elapsed": fmt_elapsed(s_elapsed),
        "rate": pass_rate_str(s_pass, s_fail, s_skip),
        "cases": [
            {
                "name": c["name"],
                "action": c["action"],
                "elapsed": fmt_elapsed(c["elapsed"]),
                "failLines": failure_snippet(c["outputs"]) if c["action"] == "fail" else [],
            }
            for c in sorted_cases
        ],
    })

for idx, s in enumerate(suite_data):
    s["_idx"] = idx

data = {
    "meta": {
        "ver": ver, "api": api, "commit": commit, "go_ver": go_ver,
        "sub_versions": sub_versions,
        "rate": rate, "start": start_time, "end": end_time,
        "_title": json_path.name,
    },
    "stats": {
        "total": total, "passed": passed, "failed": failed,
        "skipped": skipped, "unknown": unknown,
        "rate_cls": "g" if passed > 0 else "u",
    },
    "suites": suite_data,
}

html = build_html(data)

with open(output_path, "w") as f:
    f.write(html)

print(f"Generated: {output_path}")
print(f"  Total   : {total}")
print(f"  Passed  : {passed}")
print(f"  Failed  : {failed}")
print(f"  Skipped : {skipped}")
print(f"  Unknown : {unknown}")
print(f"  Rate    : {rate}")
