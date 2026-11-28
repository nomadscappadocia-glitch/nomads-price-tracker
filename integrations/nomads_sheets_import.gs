// Paste into a NEW file in the price spreadsheet's bound Apps Script project.
// Store a read-only GitHub fine-grained token in Script Properties, never in code.
const NOMADS_REPO = "nomadscappadocia-glitch/nomads-price-tracker";
const NOMADS_API = "https://api.github.com/repos/" + NOMADS_REPO;
const NOMADS_ZONE = "Europe/Istanbul";
function importNomadsPrices() {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(1000)) return;
  try {
    const props = PropertiesService.getScriptProperties();
    const token = props.getProperty("NOMADS_GITHUB_TOKEN");
    if (!token) throw new Error("Set NOMADS_GITHUB_TOKEN in Script Properties first.");
    const active = SpreadsheetApp.getActiveSpreadsheet();
    const savedId = props.getProperty("NOMADS_PRICE_SHEET_ID");
    const ss = savedId ? SpreadsheetApp.openById(savedId) : active;
    if (!ss || !ss.getSheetByName("Booking.com") || !ss.getSheetByName("Agoda")) {
      throw new Error("Run from the correct price tracker spreadsheet.");
    }
    if (!savedId) props.setProperty("NOMADS_PRICE_SHEET_ID", ss.getId());
    const runs = nomadsGetJson_(NOMADS_API + "/actions/workflows/nomads-competitor-scan.yml/runs?status=completed&per_page=15", token).workflow_runs || [];
    let inserted = 0;
    for (const run of runs.reverse()) {
      const runDay = Utilities.formatDate(new Date(run.created_at), NOMADS_ZONE, "yyyy-MM-dd");
      if (runDay < "2026-11-28" || runDay > "2026-12-31") continue;
      const targets = [["booking", "Booking.com", "EUR"], ["agoda", "Agoda", "USD"]].map(([platform, tab, currency]) => {
        const sheet = ss.getSheetByName(tab);
        const last = sheet.getLastRow();
        const existing = last > 1 ? sheet.getRange(2, 2, last - 1, 2).getDisplayValues() : [];
        return {platform, sheet, currency, keys: new Set(existing.map(([hotel, id]) => id + "|" + hotel)),
                hasRun: existing.some(([, id]) => id === String(run.id))};
      });
      // Previously imported runs are immutable, including deliberately blank results.
      if (targets.every(t => t.hasRun)) continue;
      const artifacts = nomadsGetJson_(NOMADS_API + "/actions/runs/" + run.id + "/artifacts", token).artifacts || [];
      for (const t of targets) {
        const artifact = artifacts.find(a => a.name === "competitors-" + t.platform && !a.expired);
        if (!artifact) continue;
        const files = nomadsDownloadZip_(artifact.id, token);
        const csv = files.find(f => f.getName().split("/").pop() === "summary.csv");
        if (!csv) continue;
        inserted += nomadsAppend_(t, run, Utilities.parseCsv(csv.getDataAsString("UTF-8")));
      }
    }
    console.log("Nomads: appended " + inserted + " hotel snapshots.");
  } finally {
    lock.releaseLock();
  }
}
function nomadsGetJson_(url, token) {
  const response = UrlFetchApp.fetch(url, {headers:{Authorization:"Bearer " + token,Accept:"application/vnd.github+json"},muteHttpExceptions:true});
  if (response.getResponseCode() !== 200) throw new Error("GitHub API HTTP " + response.getResponseCode());
  return JSON.parse(response.getContentText());
}
function nomadsDownloadZip_(id, token) {
  let response = UrlFetchApp.fetch(NOMADS_API + "/actions/artifacts/" + id + "/zip", {
    headers:{Authorization:"Bearer " + token,Accept:"application/vnd.github+json"},
    followRedirects:false,muteHttpExceptions:true
  });
  if ([301,302,303,307,308].includes(response.getResponseCode())) {
    const headers = response.getAllHeaders();
    const key = Object.keys(headers).find(k => k.toLowerCase() === "location");
    const url = key ? String(headers[key]) : "";
    if (!url.startsWith("https://")) throw new Error("Invalid artifact download redirect.");
    // Do not forward the GitHub token to the artifact storage service.
    response = UrlFetchApp.fetch(url,{muteHttpExceptions:true});
  }
  if (response.getResponseCode() !== 200) throw new Error("Artifact download HTTP " + response.getResponseCode());
  return Utilities.unzip(response.getBlob().setContentType("application/zip"));
}
function nomadsAppend_(target, run, csv) {
  if (csv.length < 2) return 0;
  const columns = csv[0];
  const required = ["scan_date","hotel","platform","checkin","checkout","currency","price","room","status","tax_inclusion"];
  if (required.some(c => !columns.includes(c))) throw new Error("Unexpected CSV header.");
  const sheet = target.sheet;
  const header = sheet.getRange(1,1,1,sheet.getLastColumn()).getDisplayValues()[0];
  if (header.slice(0,3).join("|") !== "Scan time (TRT)|Hotel|GitHub run") throw new Error("Price tab layout changed.");
  const groups = new Map();
  const start = Utilities.formatDate(new Date(run.created_at),NOMADS_ZONE,"yyyy-MM-dd HH:mm:ss");
  for (const row of csv.slice(1)) {
    if (row.length !== columns.length) continue;
    const a = Object.fromEntries(columns.map((c,i)=>[c,row[i]]));
    if (a.platform !== target.platform || a.currency !== target.currency ||
        !a.hotel || /^[=+@-]/.test(a.hotel) ||
        a.scan_date < "2026-11-28" || a.scan_date > "2026-12-31") continue;
    const index = header.indexOf(a.checkin);
    if (index < 3 || !/^\d{4}-\d{2}-\d{2}$/.test(a.checkin)) continue;
    const expected = new Date(a.checkin + "T00:00:00Z");
    expected.setUTCDate(expected.getUTCDate()+1);
    if (expected.toISOString().slice(0,10) !== a.checkout) continue;
    const key = String(run.id)+"|"+a.hotel;
    if (target.keys.has(key)) continue;
    if (!groups.has(key)) {
      const values = Array(header.length).fill("");
      const notes = Array(header.length).fill("");
      values[0]=start; values[1]=a.hotel; values[2]=String(run.id);
      notes[0]="Workflow creation time (Türkiye time); exact per-property collection time may differ.";
      groups.set(key,{values,notes});
    }
    const g = groups.get(key);
    const price = Number(a.price);
    if (a.status === "indicative_unverified" && a.price && Number.isFinite(price) && price > 0) g.values[index]=price;
    g.notes[index]=a.status+"; tax inclusion: "+a.tax_inclusion+(a.room?"; room: "+a.room:"");
  }
  const records = [...groups.values()];
  if (!records.length) return 0;
  const first = sheet.getLastRow()+1;
  const end = first+records.length-1;
  if (end > sheet.getMaxRows()) sheet.insertRowsAfter(sheet.getMaxRows(),end-sheet.getMaxRows());
  sheet.getRange(first,1,records.length,3).setNumberFormat("@");
  const range=sheet.getRange(first,1,records.length,header.length);
  range.setValues(records.map(r=>r.values));
  range.setNotes(records.map(r=>r.notes));
  sheet.getRange(first,4,records.length,header.length-3).setNumberFormat(target.currency==="EUR"?'"€"0.00':'"$"0.00');
  return records.length;
}
