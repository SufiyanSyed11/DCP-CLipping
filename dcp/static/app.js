// DCP Clipper front end. Plain JavaScript, no build step.
const $ = (q) => document.querySelector(q);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
let S = null, cur = { slug: "", n: null }, clip = null, lastRunning = "", lastClick = null, stamp = Date.now();

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { alert(j.error || "Something went wrong."); throw new Error(j.error); }
  return j;
}

const project = () => S.projects.find((p) => p.slug === cur.slug);
const save = async (patch) => { clip = await api(`/api/clip/${cur.slug}/${cur.n}`, patch); };
const run = (steps, n = cur.n) => api("/api/run", { slug: cur.slug, n, steps }).then(poll);

// ------------------------------------------------------------------ polling
async function poll() {
  S = await (await fetch("/api/state")).json();
  $("#badges").innerHTML =
    `<span class="badge ${S.ai ? "on" : "off"}" title="Local AI that picks B-roll moments">AI picker ${S.ai ? "on" : "off"}</span>` +
    `<span class="badge ${S.bgm ? "on" : "off"}" title="assets/bgm_under.mp3">Music ${S.bgm ? "found" : "missing"}</span>`;
  $("#job").textContent = S.running ? `Working: ${S.running}${S.queued ? ` (+${S.queued} waiting)` : ""}` : "";
  const log = $("#log");
  log.textContent = S.log.join("\n");
  log.scrollTop = log.scrollHeight;
  if (!cur.slug && S.projects.length) cur.slug = S.projects[S.projects.length - 1].slug;
  renderSide();
  if (lastRunning && lastRunning !== S.running && cur.n !== null) await openClip(cur.n);
  else if (!lastRunning && S.running && clip) renderClip();
  lastRunning = S.running;
}

// ------------------------------------------------------------------ sidebar
function renderSide() {
  const sel = $("#projects");
  if (document.activeElement && $("aside").contains(document.activeElement) && document.activeElement.tagName !== "SELECT") return;
  sel.innerHTML = S.projects.map((p) => `<option value="${p.slug}" ${p.slug === cur.slug ? "selected" : ""}>${esc(p.title)}</option>`).join("");
  sel.style.display = S.projects.length ? "" : "none";
  const p = project();
  if (!p) { $("#settings").innerHTML = ""; $("#clips").innerHTML = ""; return; }
  $("#settings").innerHTML = `
    <label>Episode YouTube ID</label><input data-k="episode" value="${esc(p.episode)}">
    <label>Or a full episode file on this PC (optional)</label><input data-k="local_file" value="${esc(p.local_file)}" placeholder="D:\\...\\episode.mp4">
    <label>Pack folder prefix</label><input data-k="show" value="${esc(p.show)}">
    <label>Caption name fixes, one per line (heard = shown)</label>
    <textarea data-k="fixes" rows="3" placeholder="sir gone = Gane">${esc(p.fixes)}</textarea>
    <button id="buildall" class="primary" style="width:100%;margin-bottom:12px">Build all ${p.clips.length} clips</button>`;
  document.querySelectorAll("#settings [data-k]").forEach((el) => {
    el.onchange = () => api(`/api/project/${cur.slug}`, { [el.dataset.k]: el.value });
  });
  $("#buildall").onclick = () => confirm(`Build all ${p.clips.length} clips now? This can take a while.`) &&
    run(["find", "cut", "broll", "render"], "all");
  $("#clips").innerHTML = p.clips.map((c) => `
    <div class="clip ${c.n === cur.n ? "sel" : ""}" data-n="${c.n}">
      <span class="dot ${c.error ? "err" : c.status}" title="${esc(c.error || c.status)}"></span>
      <span>${c.n}. ${esc(c.title)}</span></div>`).join("");
  document.querySelectorAll(".clip").forEach((el) => { el.onclick = () => openClip(+el.dataset.n); });
}

$("#projects").onchange = (e) => { cur = { slug: e.target.value, n: null }; clip = null; $("#main").innerHTML = ""; renderSide(); };
$("#file").onchange = async (e) => {
  const fd = new FormData();
  fd.append("file", e.target.files[0]);
  const r = await fetch("/api/upload", { method: "POST", body: fd });
  const j = await r.json();
  e.target.value = "";
  if (!r.ok) return alert(j.error);
  cur = { slug: j.slug, n: null };
  await poll();
};

// ------------------------------------------------------------------ clip view
async function openClip(n) {
  cur.n = n;
  clip = await api(`/api/clip/${cur.slug}/${n}`);
  stamp = Date.now();
  renderSide();
  renderClip();
}

const base = () => `/work/${cur.slug}/clip${String(cur.n).padStart(2, "0")}`;
const has = (...st) => st.includes(clip.status);
const thumbUrl = (i, k) => { const c = clip.cands[i][k]; return `/api/thumb/${cur.slug}/${cur.n}/${i}/${k}?t=${c.t}&fx=${c.fx}&v=${stamp}`; };

function renderClip() {
  const c = clip, busy = !!S.running;
  const cutDone = has("cut", "broll", "rendered", "packed") && c.tokens.length;
  let h = `<h2>${c.n}. ${esc(c.title)}</h2>
    <div class="dim">${esc(c.hook_payoff)}</div>
    <div class="dim small">Episode time: ${esc(c.source_text)}</div>`;
  if (c.notes) h += `<div class="note"><b>Slate note, check by hand:</b> ${esc(c.notes)}</div>`;
  if (c.error) h += `<div class="err">${esc(c.error)}</div>`;
  h += `<div class="row">
      <button class="primary" data-run="find,cut,broll,render" ${busy ? "disabled" : ""}>Build this clip</button>
      <span class="dim small">or step by step:</span>
      <button data-run="find" ${busy ? "disabled" : ""}>1 Find clip</button>
      <button data-run="cut" ${busy ? "disabled" : ""}>2 Cut + captions</button>
      <button data-run="broll" ${busy ? "disabled" : ""}>3 Find B-roll</button>
      <button data-run="render" ${busy ? "disabled" : ""}>4 Render</button>
      <button data-run="pack" ${busy ? "disabled" : ""}>5 Save pack folder</button></div>`;

  h += `<h3>Hook box</h3><div class="row">
      <input id="hook" style="flex:1;min-width:300px" value="${esc(c.hook_text)}">
      <input id="emoji" style="width:60px;text-align:center" value="${esc(c.emoji)}" title="Emoji at the end">
      <span class="dim small">Zach cutaway at episode time</span>
      <input id="zach" style="width:80px" value="${esc(c.zach_time)}" placeholder="mm:ss" title="Leave empty if Zach is already on camera in the clip"></div>`;

  h += `<h3>1. The clip</h3>`;
  if (!c.words.length) h += `<p class="dim">Not downloaded yet. Press “Build this clip” or “1 Find clip”.</p>`;
  else {
    h += `<p class="dim small">Blue words are in the clip. Click a word to add or remove it (Shift-click for a range), then press “2 Cut + captions”.
      ${c.match ? `Start phrase match ${Math.round(c.match.start_match * 100)}%, payoff match ${Math.round(c.match.end_match * 100)}%.` : ""}</p>
      <div id="words">${c.words.map((w, i) => `<span data-i="${i}" class="${c.keep[i] ? "k" : ""}" title="${w[1]}s">${esc(w[0])}</span>`).join(" ")}</div>
      <div class="row small"><span class="dim">Nudge the cut (seconds):</span> start <input id="adjs" type="number" step="0.05" style="width:80px" value="${c.adj.start || 0}">
      end <input id="adje" type="number" step="0.05" style="width:80px" value="${c.adj.end || 0}"></div>`;
  }

  if (cutDone) {
    h += `<h3>2. Captions <span class="dim">(${c.dur}s after pause removal)</span></h3>
      <div class="result"><video controls preload="metadata" src="${base()}/P1.mp4?v=${stamp}"></video>
      <div style="flex:1;min-width:300px"><p class="dim small">Fix any misheard word here. Swear words are bleeped and starred automatically.</p>
      <div id="caps">${c.tokens.map((t, i) => `<input data-i="${i}" value="${esc(t[0])}" size="${Math.max(2, t[0].length)}" title="${t[1]}s">`).join("")}</div></div></div>`;
  }

  h += `<h3>3. B-roll</h3>`;
  if (c.broll_notes) h += `<div class="note">${esc(c.broll_notes)}</div>`;
  c.broll.forEach((it, i) => {
    const cl = c.cands[i] || [], pk = Math.min(c.picks[i] || 0, Math.max(0, cl.length - 1)), p = cl[pk];
    h += `<div class="item"><div class="row" style="margin:0">
        <b>${i + 1}</b>
        <input data-b="${i}" data-f="match" value="${esc(it.match)}" style="flex:1" title="What the shot should show">
        <input data-b="${i}" data-f="search" value="${esc(it.search)}" style="flex:1" title="YouTube search words">
        <button data-del="${i}" title="Remove this line">✕</button></div>`;
    if (cl.length) {
      h += `<div class="cands">${cl.map((x, k) => `<div class="cand ${k === pk ? "sel" : ""}" data-i="${i}" data-k="${k}">
          <img loading="lazy" src="${thumbUrl(i, k)}">
          <div class="small">${x.flags.map((f) => `<span class="flag">⚠ ${esc(f)}</span>`).join("")}<span class="dim">${esc(x.title)}</span></div></div>`).join("")}</div>
        <div class="row small"><span class="dim">Chosen shot:</span> starts at
          <input data-t="${i}" type="number" step="0.5" min="0" style="width:80px" value="${p.t}"> s &nbsp; crop left
          <input data-fx="${i}" type="range" min="0" max="1" step="0.02" value="${p.fx}"> right
          <a class="dim" target="_blank" href="https://www.youtube.com/watch?v=${esc(p.vid)}&t=${Math.floor(p.t)}s">open source</a></div>`;
    } else h += `<p class="dim small" style="margin:8px 0 0">No shots yet. Press “3 Find B-roll”, or add one by hand.</p>`;
    h += `<div class="row small"><span class="dim">Add by hand:</span>
        <input data-ref="${i}" placeholder="YouTube link, video ID or file path" style="flex:1">
        at <input data-reft="${i}" placeholder="m:ss" style="width:70px">
        <button data-add="${i}" ${busy ? "disabled" : ""}>Add</button></div></div>`;
  });
  h += `<button id="addline">+ Add a B-roll line</button>`;

  if (cutDone && c.slots.length) {
    h += `<h3>Shot timing <span class="dim">(each shot lands on the words it shows)</span></h3>
      <table><tr><th>Time</th><th>Words spoken</th><th>Shows</th><th>Why</th></tr>
      ${c.slots.map((s, i) => `<tr><td>${s.start.toFixed(1)}–${s.end.toFixed(1)}s</td>
        <td>${esc(c.tokens.filter((t) => t[1] >= s.start - 0.05 && t[1] < s.end - 0.05).map((t) => t[0]).join(" "))}</td>
        <td><select data-slot="${i}">${c.broll.map((b, k) => `<option value="${k}" ${k === s.item ? "selected" : ""}>${k + 1}. ${esc(b.match)}</option>`).join("")}</select></td>
        <td class="dim small">${s.word ? `said “${esc(s.word)}”` : "fills the gap"}</td></tr>`).join("")}</table>
      <div class="row"><button id="retime">Re-match shots to the words</button></div>`;
  }

  if (has("rendered", "packed")) {
    const q = c.qa || {};
    const g = (ok) => (ok ? "good" : "bad");
    h += `<h3>Result</h3><div class="result">
      <video controls src="${base()}/final.mp4?v=${stamp}"></video>
      <div style="flex:1;min-width:320px"><p class="qa">
        Length <b class="${g(q.under_30s)}">${q.seconds}s</b> ·
        Loudness <b class="${g(q.lufs > -15 && q.lufs < -12.5)}">${q.lufs} LUFS</b> ·
        Words intact <b class="${g(q.words_intact > 0.9)}">${Math.round(q.words_intact * 100)}%</b> ·
        Bleeps ${q.bleeps}</p>
        ${c.pack ? `<p>Pack folder: <b>${esc(c.pack)}</b></p>` : `<p class="dim">Happy with it? Press “5 Save pack folder”. Files go to ${esc(S.output_dir)}</p>`}
        <p class="dim small">Check every frame below for women, on-screen text, cut-off faces and wrong shots before posting.</p>
        <img src="${base()}/sheet.jpg?v=${stamp}"></div></div>`;
  }
  $("#main").innerHTML = h;
  wire();
}

function wire() {
  const m = $("#main"), all = (q) => m.querySelectorAll(q);
  const rerender = async (patch) => { await save(patch); renderClip(); };
  all("[data-run]").forEach((b) => { b.onclick = () => run(b.dataset.run.split(",")); });
  $("#hook").onchange = (e) => save({ hook_text: e.target.value });
  $("#emoji").onchange = (e) => save({ emoji: e.target.value.trim() });
  $("#zach").onchange = (e) => save({ zach_time: e.target.value.trim() });
  all("#words span").forEach((el) => {
    el.onclick = (ev) => {
      const i = +el.dataset.i, on = !clip.keep[i];
      const [a, b] = ev.shiftKey && lastClick !== null ? [Math.min(i, lastClick), Math.max(i, lastClick)] : [i, i];
      for (let k = a; k <= b; k++) clip.keep[k] = on;
      lastClick = i;
      all("#words span").forEach((s) => s.classList.toggle("k", clip.keep[+s.dataset.i]));
      save({ keep: clip.keep });
    };
  });
  const adj = () => save({ adj: { start: +$("#adjs").value || 0, end: +$("#adje").value || 0 } });
  if ($("#adjs")) { $("#adjs").onchange = adj; $("#adje").onchange = adj; }
  all("#caps input").forEach((el) => {
    el.onchange = () => { clip.tokens[+el.dataset.i][0] = el.value.trim(); save({ tokens: clip.tokens.filter((t) => t[0]) }); };
  });
  all("[data-b]").forEach((el) => {
    el.onchange = () => { clip.broll[+el.dataset.b][el.dataset.f] = el.value.trim(); rerender({ broll: clip.broll }); };
  });
  all("[data-del]").forEach((el) => {
    el.onclick = () => {
      const i = +el.dataset.del;
      clip.broll.splice(i, 1); clip.cands.splice(i, 1); clip.picks.splice(i, 1);
      rerender({ cands: clip.cands, picks: clip.picks, broll: clip.broll });
    };
  });
  $("#addline").onclick = () => {
    clip.broll.push({ search: "", match: "", hint: "", fixed: null });
    rerender({ broll: clip.broll });
  };
  all(".cand").forEach((el) => {
    el.onclick = () => { clip.picks[+el.dataset.i] = +el.dataset.k; rerender({ picks: clip.picks }); };
  });
  const tweak = (el, key) => {
    const i = +el.dataset[key === "t" ? "t" : "fx"], k = Math.min(clip.picks[i] || 0, clip.cands[i].length - 1);
    clip.cands[i][k][key] = +el.value;
    m.querySelector(`.cand[data-i="${i}"][data-k="${k}"] img`).src = thumbUrl(i, k);
  };
  all("[data-t]").forEach((el) => { el.oninput = () => tweak(el, "t"); el.onchange = () => save({ cands: clip.cands }); });
  all("[data-fx]").forEach((el) => { el.oninput = () => tweak(el, "fx"); el.onchange = () => save({ cands: clip.cands }); });
  all("[data-add]").forEach((el) => {
    el.onclick = async () => {
      const i = el.dataset.add, ref = m.querySelector(`[data-ref="${i}"]`).value;
      const parts = (m.querySelector(`[data-reft="${i}"]`).value || "0").split(":").map(Number);
      if (!ref.trim()) return;
      await api("/api/manual", { slug: cur.slug, n: cur.n, item: +i, ref, t: parts.reduce((a, b) => a * 60 + (b || 0), 0) });
      poll();
    };
  });
  all("[data-slot]").forEach((el) => {
    el.onchange = () => { clip.slots[+el.dataset.slot].item = +el.value; clip.slots[+el.dataset.slot].word = ""; rerender({ slots: clip.slots }); };
  });
  if ($("#retime")) $("#retime").onclick = () => rerender({ retime: true });
}

poll();
setInterval(poll, 1500);
