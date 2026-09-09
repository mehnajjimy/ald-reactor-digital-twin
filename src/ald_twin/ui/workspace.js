/* UI state and presentation only. All flow, validation and solves stay in Python. */
const byId = id => document.getElementById(id);
const token = document.querySelector('meta[name="workspace-token"]').content;
const isDesktop = document.querySelector('meta[name="desktop"]').content === 'true';
const recipeFields = [...document.querySelectorAll('[data-recipe]')];
const labels = {pass:'Meets limits', fail:'Fails limits', unresolved:'Near threshold',
  unverified:'Unverified', 'outside-screen':'Outside screen'};
let processes = [], savedRuns = [], inputs = null, inspection = null, displayed = null;
let running = false, starting = false, inspecting = false, connected = true;
let inspectionVersion = 0, selectionVersion = 0, inspectTimer, activeId = null;
let jobVersion = 0;
let audioEnabled = false, playingAudio = null;
try { audioEnabled = localStorage.getItem('ald-sounds') === 'on'; } catch (_) {}

async function api(path, data) {
  const response = await fetch(path, {method:data === undefined ? 'GET' : 'POST',
    headers:{'Content-Type':'application/json', 'X-Workspace-Token':token},
    body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Workspace request failed');
  return result;
}

function errors(messages) {
  const panel = byId('validation');
  panel.replaceChildren(); panel.hidden = !messages.length;
  const list = document.createElement('ul');
  for (const message of messages) {
    const item = document.createElement('li'); item.textContent = message; list.append(item);
  }
  panel.append(list);
}

function playSound(cue) {
  if (!audioEnabled) return;
  if (playingAudio) playingAudio.pause();
  playingAudio = new Audio(`/audio/${cue}.wav`);
  playingAudio.volume = cue === 'click' ? 0.125 : 0.25;
  playingAudio.play().catch(() => {
    byId('status-text').textContent = 'Sound playback unavailable; the calculation is unaffected.';
  });
}

function soundLabel() {
  byId('sound-toggle').textContent = audioEnabled ? 'Sounds on' : 'Sounds off';
  byId('sound-toggle').setAttribute('aria-pressed', String(audioEnabled));
}

function controls() {
  const busy = running || starting;
  byId('run').disabled = busy || inspecting || !connected || !inspection?.runnable;
  byId('run').textContent = busy ? 'Running…' : 'Run simulation';
  byId('stop').hidden = !running;
  byId('open-inputs').disabled = busy;
  byId('saved-run').disabled = busy;
  recipeFields.forEach(field => { field.disabled = busy || !inputs; });
  document.querySelectorAll('[data-process]').forEach(button => { button.disabled = busy; });
  byId('progress').hidden = !busy;
  byId('report').disabled = !displayed?.ready;
}

const number = (value, digits=3) => value == null ? 'Unavailable' : Number(value).toFixed(digits);
const percent = value => value == null ? 'Unavailable' : number(value*100, 2);
const clearance = value => value == null ? 'Not cleared' : number(value*1000);

function fillRows(target, rows) {
  const body = byId(target); body.replaceChildren();
  for (const values of rows) {
    const row = document.createElement('tr');
    for (const value of values) {
      const cell = document.createElement('td'); cell.textContent = value ?? 'Unavailable'; row.append(cell);
    }
    body.append(row);
  }
}

function metricRows(first, second) {
  const quantities = [
    ['Minimum A completion (%)', m => percent(m.minimum_a_completion)],
    ['Maximum B remaining (%)', m => percent(m.maximum_b_remaining)],
    ['Mean turnover / cycle', m => number(m.mean_turnover, 5)],
    ['A purge clearance (ms)', m => clearance(m.purge_crossing_s?.[0])],
    ['B purge clearance (ms)', m => clearance(m.purge_crossing_s?.[1])],
    ['ZnO equivalent (Å/cycle)', m => number(m.mean_gpc_angstrom, 5)],
  ];
  return quantities.map(([label, value]) => [label, first ? value(first) : 'Unavailable',
    second ? value(second) : 'Unavailable']);
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}

function showDraft() {
  byId('draft').hidden = !displayed || JSON.stringify(canonical(inputs)) === JSON.stringify(canonical(displayed.inputs));
}

function renderInputs() {
  if (!inputs) return;
  const channel = inputs.channel || {}, chemistry = inputs.chemistry || {}, diffusion = inputs.diffusivity || {};
  const sourceRows = [
    ['Channel length', channel.length, 'm'], ['Channel width', channel.width, 'm'],
    ['Channel gap', channel.height, 'm'], ['Temperature', channel.temperature, 'K'],
    ['Outlet pressure', channel.outlet_pressure, 'Pa'], ['Carrier molar flow', channel.molar_flow, 'mol/s'],
    ['Carrier viscosity', channel.viscosity, 'Pa s'], ['Reactive interval', JSON.stringify(inputs.reactive_interval), 'm'],
    ['Inlet fraction', inputs.fraction_scale, '1'], ['A diffusion', diffusion.a?.value, 'm²/s'],
    ['B diffusion', diffusion.b?.value, 'm²/s'], ['A reference temperature', diffusion.a?.temperature, 'K'],
    ['B reference temperature', diffusion.b?.temperature, 'K'], ['A reference pressure', diffusion.a?.pressure, 'Pa'],
    ['B reference pressure', diffusion.b?.pressure, 'Pa'], ['Effective capacity', chemistry.capacity, 'mol/m²'],
    ['A rate', chemistry.rate_a, 'm³/(mol s)'], ['B rate', chemistry.rate_b, 'm³/(mol s)'],
    ['Spatial grids', Array.isArray(inputs.spatial_grids) ? inputs.spatial_grids.join(', ') : null, 'cells'],
    ['Film density', inputs.film?.density_kg_m3, 'kg/m³'],
  ];
  fillRows('input-rows', sourceRows);
  const reactor = byId('reactor-values'); reactor.replaceChildren();
  const list = document.createElement('dl');
  for (const [label, value] of [['Channel', channel.length == null ? '—' : number(channel.length*1000, 1)+' mm'],
    ['Gap', channel.height == null ? '—' : number(channel.height*1000, 1)+' mm'],
    ['Temperature', channel.temperature == null ? '—' : number(channel.temperature-273.15, 0)+' °C'],
    ['Outlet', channel.outlet_pressure == null ? '—' : number(channel.outlet_pressure, 0)+' Pa']]) {
    const term = document.createElement('dt'), description = document.createElement('dd');
    term.textContent = label; description.textContent = value; list.append(term, description);
  }
  reactor.append(list);
  byId('process-name').textContent = inputs.name || 'Imported inputs';
  const sources = byId('sources'); sources.replaceChildren();
  for (const [name, record] of Object.entries(inputs.provenance || {})) {
    const title = document.createElement('h3'), text = document.createElement('p');
    title.textContent = name; text.textContent = [record?.source, record?.validity].filter(Boolean).join(' ');
    sources.append(title, text);
  }
  const flow = inspection?.flow;
  byId('recipe-time').textContent = flow
    ? `τ = ${number(flow.residence_s*1000, 4)} ms · Cycle ${number(flow.segment_duration_s.reduce((a,b) => a+b, 0)*1000)} ms`
    : 'Complete the required inputs.';
  const ratios = recipeFields.map(field => Number(field.value));
  document.querySelectorAll('.rx-sequence i').forEach((bar, i) => { bar.style.flex = ratios[i] > 0 ? ratios[i] : 1; });
  showDraft();
}

async function inspectCurrent() {
  const version = ++inspectionVersion;
  inspecting = true; controls();
  try {
    const next = await api('/api/inspect', inputs);
    if (version !== inspectionVersion) return;
    inspection = next; errors(next.issues); renderInputs();
  } catch (error) {
    if (version === inspectionVersion) { inspection = null; errors([error.message]); }
  } finally {
    if (version === inspectionVersion) { inspecting = false; controls(); }
  }
}

function setInputs(data) {
  inputs = structuredClone(data);
  recipeFields.forEach(field => { field.value = inputs.recipe?.[field.dataset.recipe] ?? ''; });
  document.querySelectorAll('[data-process]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.process === inputs.id));
  });
  return inspectCurrent();
}

function drawChart() {
  const svg = byId('chart'), record = displayed?.record;
  if (byId('results').hidden || byId('profile-panel').hidden || !record?.profile) return;
  const width = Math.max(220, svg.getBoundingClientRect().width), height = 230;
  const left = 48, right = 15, top = 24, bottom = 43;
  const xs = record.profile.z_m, ys = record.profile.turnover;
  const mixed = record.models.mixed?.metrics.mean_turnover;
  const samples = mixed == null ? ys : ys.concat(mixed);
  const minimum = Math.min(...samples), maximum = Math.max(...samples);
  const padding = Math.max(.005, (maximum-minimum)*.2), low = minimum-padding, high = maximum+padding;
  const length = displayed.inputs.channel.length*1000;
  const x = value => left + value/length*(width-left-right);
  const y = value => top + (high-value)/(high-low)*(height-top-bottom);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.replaceChildren();
  function mark(tag, attributes, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key,value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    svg.append(node);
  }
  mark('text', {x:left, y:12}, 'Turnover / cycle');
  for (let i=0; i<4; i++) {
    const value = low+(high-low)*i/3;
    mark('line', {x1:left, x2:width-right, y1:y(value), y2:y(value), stroke:'#e9edf0'});
    mark('text', {x:left-8, y:y(value)+4, 'text-anchor':'end'}, value.toFixed(3));
  }
  const ticks = width < 360 ? 2 : 5;
  for (let i=0; i<=ticks; i++) {
    const value = length*i/ticks;
    mark('line', {x1:x(value), x2:x(value), y1:top, y2:height-bottom, stroke:'#f0f2f4'});
    mark('text', {x:x(value), y:height-bottom+19, 'text-anchor':i===0?'start':i===ticks?'end':'middle'}, Number(value.toPrecision(3)));
  }
  mark('text', {x:left+(width-left-right)/2, y:height-4, 'text-anchor':'middle'}, 'Channel position (mm)');
  if (mixed != null) mark('line', {x1:left, x2:width-right, y1:y(mixed), y2:y(mixed), stroke:'#708391', 'stroke-width':1.5, 'stroke-dasharray':'5 4'});
  mark('path', {d:xs.map((value,i) => `${i?'L':'M'}${x(value*1000)},${y(ys[i])}`).join(' '),
    fill:'none', stroke:'#5aa9d6', 'stroke-width':2.3});
}

function renderResult(origin='Saved output') {
  const record = displayed?.record, models = record?.models || {};
  const hasModels = Boolean(models.mixed || models.spatial);
  byId('result-data').hidden = !hasModels;
  byId('empty-result').hidden = hasModels;
  byId('empty-result').textContent = record ? 'No verified spatial result is available for this run.'
    : 'Choose a process and run a recipe, or open a saved result.';
  byId('result-origin').textContent = displayed ? `${origin} · ${displayed.id}` : 'No result selected';
  byId('numerical').textContent = record?.status || '—';
  byId('numerical').className = record?.numerical_acceptance ? 'rx-pass' : 'rx-review';
  byId('feasible').textContent = labels[record?.recipe_feasibility] || '—';
  byId('feasible').className = record?.recipe_feasibility === 'pass' ? 'rx-pass' : 'rx-review';
  byId('grid').textContent = record?.accepted_cells ? `${record.accepted_cells} cells · verified` : 'Not verified';
  byId('profile-panel').hidden = !record?.profile;
  fillRows('metrics', metricRows(models.mixed?.metrics, models.spatial?.metrics));
  byId('film-note').textContent = models.spatial?.metrics.film_status || '';
  byId('result-reason').hidden = !record?.reason;
  byId('result-reason').textContent = record?.reason || '';
  byId('attempt-panel').hidden = !record?.attempts?.length;
  fillRows('attempts', (record?.attempts || []).map(row => [row.label, row.cells, row.status]));
  const spatial = models.spatial?.metrics;
  fillRows('diagnostics', spatial ? [
    ['Relative turnover spread', number(spatial.relative_turnover_spread, 5)],
    ['A purge residual (scaled)', number(spatial.purge_a_residual, 5)],
    ['B purge residual (scaled)', number(spatial.purge_b_residual, 5)],
  ] : []);
  showDraft(); controls(); drawChart();
}

async function openRun(name, adoptInputs=true, origin='Saved output') {
  const version = ++selectionVersion;
  const result = await api('/api/run/'+encodeURIComponent(name));
  if (version !== selectionVersion) return;
  displayed = result;
  if (adoptInputs) await setInputs(result.inputs);
  if (version !== selectionVersion) return;
  byId('saved-run').value = name;
  renderResult(origin);
}

function runLabel(row) {
  const date = row.started_at ? new Date(row.started_at).toLocaleString() : row.id;
  return `${row.process_id} · ${date} · ${row.status}`;
}

function fillRunSelect(id, rows, placeholder) {
  const select = byId(id), previous = select.value;
  select.replaceChildren(new Option(placeholder, ''));
  rows.forEach(row => select.add(new Option(runLabel(row), row.id)));
  if (rows.some(row => row.id === previous)) select.value = previous;
}

async function refreshRuns() {
  savedRuns = await api('/api/runs');
  fillRunSelect('saved-run', savedRuns, savedRuns.length ? 'Choose saved run' : 'No saved runs');
  const ready = savedRuns.filter(row => row.ready);
  byId('compare-empty').textContent = ready.length >= 2 ? 'Choose two saved runs.'
    : 'Complete two runs to compare their saved outputs.';
  fillRunSelect('compare-first', ready, 'Choose run');
  fillRunSelect('compare-second', ready, 'Choose run');
  if (displayed) byId('saved-run').value = displayed.id;
}

async function compareSelected() {
  const first = byId('compare-first').value, second = byId('compare-second').value;
  byId('compare-empty').hidden = Boolean(first && second);
  byId('comparison-table').hidden = true;
  if (!first || !second) return;
  try {
    const result = await api('/api/compare', [first, second]);
    // Ignore a response for an earlier selection.
    if (first !== byId('compare-first').value || second !== byId('compare-second').value) return;
    const [a,b] = result.runs;
    fillRows('comparison', [
      ['Process', a.process_name, b.process_name],
      ['Recipe (τ)', Object.values(a.recipe).join(' / '), Object.values(b.recipe).join(' / ')],
      ['Numerical', a.status, b.status], ['Recipe constraints', labels[a.recipe_feasibility], labels[b.recipe_feasibility]],
      ...metricRows(a.models?.spatial?.metrics, b.models?.spatial?.metrics),
    ]);
    byId('comparison-table').hidden = false;
  } catch (error) {
    if (first === byId('compare-first').value && second === byId('compare-second').value) errors([error.message]);
  }
}

function setView(view) {
  document.querySelectorAll('[data-view]').forEach(button => {
    const selected = button.dataset.view === view;
    button.setAttribute('aria-pressed', String(selected)); byId(button.dataset.view).hidden = !selected;
  });
  drawChart();
}

async function download(text, filename, type) {
  if (isDesktop) {
    try { await api('/api/desktop/export', {text, filename}); }
    catch (error) { errors([error.message]); }
    return;
  }
  const url = URL.createObjectURL(new Blob([text], {type}));
  const link = document.createElement('a'); link.href = url; link.download = filename; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function poll() {
  const version = jobVersion;
  try {
    const {active} = await api('/api/state');
    if (version !== jobVersion) return;
    connected = true;
    running = Boolean(active?.running); controls();
    if (active) {
      byId('status-text').textContent = active.record.stage || active.record.status;
      byId('stop').disabled = Boolean(active.stop_requested);
      if (running) activeId = active.id;
      else if (activeId === active.id) {
        activeId = null;
        const selection = selectionVersion;
        try {
          await refreshRuns();
          if (selection !== selectionVersion || version !== jobVersion) return;
          await openRun(active.id, true, 'New calculation');
          if (active.ready && version === jobVersion) playSound('complete');
        } catch (error) { errors([error.message]); }
      }
    } else if (!starting) byId('status-text').textContent = 'Ready';
  } catch (error) {
    if (version !== jobVersion) return;
    connected = false; controls(); byId('status-text').textContent = 'Workspace unavailable. Reconnecting…';
  } finally { setTimeout(poll, 1000); }
}

async function initialize() {
  if (isDesktop) audioEnabled = await api('/api/desktop/sound');
  soundLabel();
  processes = await api('/api/processes');
  const list = byId('process-list');
  for (const process of processes) {
    const button = document.createElement('button'); button.className = 'rx-process';
    button.dataset.process = process.inputs.id; button.setAttribute('aria-pressed', 'false');
    const title = document.createElement('span'), detail = document.createElement('small');
    title.textContent = process.inputs.id === 'synthetic-zno' ? 'ZnO equivalent'
      : process.inputs.id === 'synthetic-ab' ? 'Fictional A / B' : process.inputs.name;
    detail.textContent = process.inputs.id === 'synthetic-zno' ? 'DEZ placeholder' : 'Synthetic';
    title.append(detail); button.append(title); list.append(button);
    button.addEventListener('click', async () => {
      const selection = ++selectionVersion;
      try {
        displayed = null; byId('saved-run').value = '';
        await setInputs(process.inputs); renderResult(); playSound('click');
        if (selection !== selectionVersion) return;
        const latest = savedRuns.find(row => row.process_id === process.inputs.id && row.ready);
        if (latest) await openRun(latest.id, false);
      } catch (error) { errors([error.message]); }
    });
  }
  await refreshRuns();
  const initial = await api('/api/state');
  running = Boolean(initial.active?.running);
  if (running) activeId = initial.active.id;
  await setInputs(running ? initial.active.inputs
    : (processes.find(row => row.inputs.id === 'synthetic-zno') || processes[0]).inputs);
  const latest = savedRuns.find(row => row.process_id === inputs.id && row.ready);
  try { if (latest) await openRun(latest.id, false); else renderResult(); }
  catch (error) { errors([error.message]); renderResult(); }
  poll();
}

byId('sound-toggle').addEventListener('click', async () => {
  const previous = audioEnabled;
  byId('sound-toggle').disabled = true;
  audioEnabled = !audioEnabled; soundLabel();
  try {
    if (isDesktop) await api('/api/desktop/sound', audioEnabled);
    try { localStorage.setItem('ald-sounds', audioEnabled ? 'on' : 'off'); } catch (_) {}
  } catch (error) {
    audioEnabled = previous; soundLabel(); errors([error.message]);
  } finally {
    byId('sound-toggle').disabled = false;
  }
  if (audioEnabled) playSound('click'); else if (playingAudio) playingAudio.pause();
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  setView(button.dataset.view); playSound('click');
}));
recipeFields.forEach(field => field.addEventListener('input', () => {
  if (!inputs.recipe || Array.isArray(inputs.recipe) || typeof inputs.recipe !== 'object') inputs.recipe = {};
  inputs.recipe[field.dataset.recipe] = field.value === '' ? null : Number(field.value);
  inspecting = true; inspectionVersion++; controls(); showDraft(); clearTimeout(inspectTimer);
  inspectTimer = setTimeout(inspectCurrent, 180);
}));
byId('saved-run').addEventListener('change', async event => {
  if (!event.target.value) return;
  try { await openRun(event.target.value); playSound('click'); }
  catch (error) { errors([error.message]); }
});
['compare-first','compare-second'].forEach(id => byId(id).addEventListener('change', compareSelected));
byId('open-inputs').addEventListener('click', () => byId('input-file').click());
byId('input-file').addEventListener('change', async event => {
  const file = event.target.files[0]; if (!file) return;
  try {
    if (file.size > 524288) throw new Error('Input file must be at most 512 KB');
    const data = JSON.parse(await file.text());
    if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('Inputs must be a JSON object');
    selectionVersion++; displayed = null; byId('saved-run').value = '';
    await setInputs(data); renderResult(); setView('inputs'); playSound('click');
  } catch (error) { errors([error.message]); }
  event.target.value = '';
});
byId('save-inputs').addEventListener('click', () => {
  if (inputs) download(JSON.stringify(inputs, null, 2)+'\n', 'process-inputs.json', 'application/json');
});
byId('report').addEventListener('click', async () => {
  const name = displayed.id;
  try {
    const response = await fetch('/api/report/'+encodeURIComponent(name), {headers:{'X-Workspace-Token':token}});
    if (!response.ok) throw new Error((await response.json()).error);
    download(await response.text(), name+'-report.md', 'text/markdown');
  } catch (error) { errors([error.message]); }
});
byId('run').addEventListener('click', async () => {
  jobVersion++; selectionVersion++;
  starting = true; controls(); errors([]);
  try {
    const {active} = await api('/api/start', inputs);
    running = true; activeId = active.id; setView('results');
    byId('status-text').textContent = 'Starting solver'; playSound('crystal');
  } catch (error) { errors([error.message]); }
  finally { jobVersion++; starting = false; controls(); }
});
byId('stop').addEventListener('click', async () => {
  byId('stop').disabled = true;
  try { await api('/api/stop', {}); byId('status-text').textContent = 'Stopping; retaining completed attempts'; }
  catch (error) { errors([error.message]); byId('stop').disabled = false; }
});
new ResizeObserver(drawChart).observe(byId('chart'));
initialize().catch(error => { errors([error.message]); byId('status-text').textContent = 'Could not load workspace'; });
