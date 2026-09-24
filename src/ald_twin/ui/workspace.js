/* ui state and presentation only. all flow, validation and solves stay in python. */

// ---- page setup ----

const byId = id => document.getElementById(id);
// the per-session token the python server checks on every api call
const token = document.querySelector('meta[name="workspace-token"]').content;
// true inside the mac desktop app, false in a normal browser
const isDesktop = document.querySelector('meta[name="desktop"]').content === 'true';
// the four recipe number boxes (A pulse, A purge, B pulse, B purge)
const recipeFields = [...document.querySelectorAll('[data-recipe]')];
// display text for each recipe feasibility result
const labels = {pass:'Meets limits', fail:'Fails limits', unresolved:'Near threshold',
  unverified:'Unverified', 'outside-screen':'Outside screen'};

// ---- fixed numbers ----

// unit conversions
const MS_PER_S = 1000;
const MM_PER_M = 1000;
const KELVIN_AT_ZERO_CELSIUS = 273.15;
// the largest inputs file the page will open (512 KB)
const MAX_INPUT_BYTES = 524288;
// wait this long after the last recipe edit before asking python to check it
const INSPECT_DELAY_MS = 180;
// how often to ask python whether a calculation is running
const POLL_INTERVAL_MS = 1000;
// how long a download link stays valid before it is released
const DOWNLOAD_LINK_MS = 1000;
// sound volumes: the click is quieter than the other cues
const CLICK_VOLUME = 0.125;
const CUE_VOLUME = 0.25;

// ---- page state ----

// process catalog and saved run list from python
let processes = [];
let savedRuns = [];
// the inputs being edited, python's check of them, and the result on screen
let inputs = null;
let inspection = null;
let displayed = null;
// busy flags for the run button and the server connection
let running = false;
let starting = false;
let inspecting = false;
let connected = true;
// version counters so a slow reply for an older request is ignored
let inspectionVersion = 0;
let selectionVersion = 0;
let jobVersion = 0;
// pending recipe check timer and the id of the job being watched
let inspectTimer;
let activeId = null;
// sound preference and the sound that is playing now
let audioEnabled = false;
let playingAudio = null;
try { audioEnabled = localStorage.getItem('ald-sounds') === 'on'; } catch (_) {}

// ---- server calls and messages ----

// send a GET (no data) or a JSON POST to the workspace server and return its reply
async function api(path, data) {
  const response = await fetch(path, {method:data === undefined ? 'GET' : 'POST',
    headers:{'Content-Type':'application/json', 'X-Workspace-Token':token},
    body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || 'Workspace request failed');
  return result;
}

// show a list of error messages in the validation panel, or hide it when empty
function errors(messages) {
  const panel = byId('validation');
  panel.replaceChildren();
  panel.hidden = !messages.length;
  const list = document.createElement('ul');
  for (const message of messages) {
    const item = document.createElement('li');
    item.textContent = message;
    list.append(item);
  }
  panel.append(list);
}

// true for a plain JSON object, false for null, arrays and other values
function isJsonObject(value) {
  if (!value) return false;
  if (Array.isArray(value)) return false;
  return typeof value === 'object';
}

// ---- sounds ----

// play one sound cue (click, crystal or complete) when sounds are on
function playSound(cue) {
  if (!audioEnabled) return;
  if (playingAudio) playingAudio.pause();
  playingAudio = new Audio(`/audio/${cue}.wav`);
  if (cue === 'click') playingAudio.volume = CLICK_VOLUME;
  else playingAudio.volume = CUE_VOLUME;
  playingAudio.play().catch(() => {
    byId('status-text').textContent = 'Sound playback unavailable; the calculation is unaffected.';
  });
}

// update the sound button text and pressed state
function soundLabel() {
  byId('sound-toggle').textContent = audioEnabled ? 'Sounds on' : 'Sounds off';
  byId('sound-toggle').setAttribute('aria-pressed', String(audioEnabled));
}

// enable or disable the buttons and fields to match the busy flags
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

// ---- number formatting ----

// fixed-decimal text for a value, or 'Unavailable' when it is missing
function number(value, digits=3) {
  if (value == null) return 'Unavailable';
  return Number(value).toFixed(digits);
}

// a fraction shown as a percent with 2 decimals
function percent(value) {
  if (value == null) return 'Unavailable';
  return number(value*100, 2);
}

// a purge clearance time in s shown in ms, or 'Not cleared'
function clearance(value) {
  if (value == null) return 'Not cleared';
  return number(value*MS_PER_S);
}

// ---- tables ----

// replace the rows of a table body with one row per list of cell values
function fillRows(target, rows) {
  const body = byId(target);
  body.replaceChildren();
  for (const values of rows) {
    const row = document.createElement('tr');
    for (const value of values) {
      const cell = document.createElement('td');
      cell.textContent = value ?? 'Unavailable';
      row.append(cell);
    }
    body.append(row);
  }
}

// rows of cycle outputs with one column for each of two metric sets
function metricRows(first, second) {
  const quantities = [
    ['Minimum A completion (%)', m => percent(m.minimum_a_completion)],
    ['Maximum B remaining (%)', m => percent(m.maximum_b_remaining)],
    ['Mean turnover / cycle', m => number(m.mean_turnover, 5)],
    ['A purge clearance (ms)', m => clearance(m.purge_crossing_s?.[0])],
    ['B purge clearance (ms)', m => clearance(m.purge_crossing_s?.[1])],
    ['ZnO equivalent (Å/cycle)', m => number(m.mean_gpc_angstrom, 5)],
  ];
  const rows = [];
  for (const [label, value] of quantities) {
    const firstText = first ? value(first) : 'Unavailable';
    const secondText = second ? value(second) : 'Unavailable';
    rows.push([label, firstText, secondText]);
  }
  return rows;
}

// ---- draft notice ----

// a copy of a value with object keys sorted, so two inputs compare by content
function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    const keys = Object.keys(value).sort();
    return Object.fromEntries(keys.map(key => [key, canonical(value[key])]));
  }
  return value;
}

// show the draft notice when the edited inputs differ from the displayed result
function showDraft() {
  if (!displayed) {
    byId('draft').hidden = true;
    return;
  }
  byId('draft').hidden = JSON.stringify(canonical(inputs)) === JSON.stringify(canonical(displayed.inputs));
}

// ---- inputs view ----

// short reactor summary rows for the side panel, with a dash for missing values
function reactorSummary(channel) {
  const channelText = channel.length == null ? '—' : number(channel.length*MM_PER_M, 1)+' mm';
  const gapText = channel.height == null ? '—' : number(channel.height*MM_PER_M, 1)+' mm';
  const temperatureText = channel.temperature == null ? '—'
    : number(channel.temperature-KELVIN_AT_ZERO_CELSIUS, 0)+' °C';
  const outletText = channel.outlet_pressure == null ? '—' : number(channel.outlet_pressure, 0)+' Pa';
  return [['Channel', channelText], ['Gap', gapText], ['Temperature', temperatureText], ['Outlet', outletText]];
}

// total cycle time in s from the segment durations
function cycleSeconds(flow) {
  let total = 0;
  for (const duration of flow.segment_duration_s) total = total+duration;
  return total;
}

// draw the inputs table, reactor summary, sources and recipe timing
function renderInputs() {
  if (!inputs) return;
  const channel = inputs.channel || {};
  const chemistry = inputs.chemistry || {};
  const diffusion = inputs.diffusivity || {};

  // required inputs table
  let grids = null;
  if (Array.isArray(inputs.spatial_grids)) grids = inputs.spatial_grids.join(', ');
  const sourceRows = [
    ['Channel length', channel.length, 'm'],
    ['Channel width', channel.width, 'm'],
    ['Channel gap', channel.height, 'm'],
    ['Temperature', channel.temperature, 'K'],
    ['Outlet pressure', channel.outlet_pressure, 'Pa'],
    ['Carrier molar flow', channel.molar_flow, 'mol/s'],
    ['Carrier viscosity', channel.viscosity, 'Pa s'],
    ['Reactive interval', JSON.stringify(inputs.reactive_interval), 'm'],
    ['Inlet fraction', inputs.fraction_scale, '1'],
    ['A diffusion', diffusion.a?.value, 'm²/s'],
    ['B diffusion', diffusion.b?.value, 'm²/s'],
    ['A reference temperature', diffusion.a?.temperature, 'K'],
    ['B reference temperature', diffusion.b?.temperature, 'K'],
    ['A reference pressure', diffusion.a?.pressure, 'Pa'],
    ['B reference pressure', diffusion.b?.pressure, 'Pa'],
    ['Effective capacity', chemistry.capacity, 'mol/m²'],
    ['A rate', chemistry.rate_a, 'm³/(mol s)'],
    ['B rate', chemistry.rate_b, 'm³/(mol s)'],
    ['Spatial grids', grids, 'cells'],
    ['Film density', inputs.film?.density_kg_m3, 'kg/m³'],
  ];
  fillRows('input-rows', sourceRows);

  // reactor summary in the side panel
  const reactor = byId('reactor-values');
  reactor.replaceChildren();
  const list = document.createElement('dl');
  for (const [label, value] of reactorSummary(channel)) {
    const term = document.createElement('dt');
    const description = document.createElement('dd');
    term.textContent = label;
    description.textContent = value;
    list.append(term, description);
  }
  reactor.append(list);
  byId('process-name').textContent = inputs.name || 'Imported inputs';

  // sources and model scope
  const sources = byId('sources');
  sources.replaceChildren();
  for (const [name, record] of Object.entries(inputs.provenance || {})) {
    const title = document.createElement('h3');
    const text = document.createElement('p');
    title.textContent = name;
    text.textContent = [record?.source, record?.validity].filter(Boolean).join(' ');
    sources.append(title, text);
  }

  // residence time and cycle time under the recipe fields
  const flow = inspection?.flow;
  if (flow) {
    const residence = number(flow.residence_s*MS_PER_S, 4);
    const cycle = number(cycleSeconds(flow)*MS_PER_S);
    byId('recipe-time').textContent = `τ = ${residence} ms · Cycle ${cycle} ms`;
  } else {
    byId('recipe-time').textContent = 'Complete the required inputs.';
  }

  // bar lengths of the recipe sequence follow the step durations
  const ratios = recipeFields.map(field => Number(field.value));
  document.querySelectorAll('.rx-sequence i').forEach((bar, i) => {
    bar.style.flex = ratios[i] > 0 ? ratios[i] : 1;
  });
  showDraft();
}

// ask python to check the current inputs, ignoring replies for older edits
async function inspectCurrent() {
  inspectionVersion += 1;
  const version = inspectionVersion;
  inspecting = true;
  controls();
  try {
    const next = await api('/api/inspect', inputs);
    if (version !== inspectionVersion) return;
    inspection = next;
    errors(next.issues);
    renderInputs();
  } catch (error) {
    if (version === inspectionVersion) {
      inspection = null;
      errors([error.message]);
    }
  } finally {
    if (version === inspectionVersion) {
      inspecting = false;
      controls();
    }
  }
}

// load a copy of new inputs into the page and start checking them
function setInputs(data) {
  inputs = structuredClone(data);
  recipeFields.forEach(field => { field.value = inputs.recipe?.[field.dataset.recipe] ?? ''; });
  document.querySelectorAll('[data-process]').forEach(button => {
    button.setAttribute('aria-pressed', String(button.dataset.process === inputs.id));
  });
  return inspectCurrent();
}

// ---- results view ----

// text-anchor for an x-axis label: first label left, last label right, others centred
function tickAnchor(i, ticks) {
  if (i === 0) return 'start';
  if (i === ticks) return 'end';
  return 'middle';
}

// draw turnover per cycle along the channel, with the 0D mixed value as a dashed line
function drawChart() {
  const svg = byId('chart');
  const record = displayed?.record;
  if (byId('results').hidden || byId('profile-panel').hidden || !record?.profile) return;

  // chart size and margins in px
  const width = Math.max(220, svg.getBoundingClientRect().width);
  const height = 230;
  const left = 48;
  const right = 15;
  const top = 24;
  const bottom = 43;

  // data and y range, padded so flat profiles still show
  const xs = record.profile.z_m;
  const ys = record.profile.turnover;
  const mixed = record.models.mixed?.metrics.mean_turnover;
  const samples = mixed == null ? ys : ys.concat(mixed);
  const minimum = Math.min(...samples);
  const maximum = Math.max(...samples);
  const padding = Math.max(.005, (maximum-minimum)*.2);
  const low = minimum-padding;
  const high = maximum+padding;
  const length = displayed.inputs.channel.length*MM_PER_M;
  const x = value => left + value/length*(width-left-right);
  const y = value => top + (high-value)/(high-low)*(height-top-bottom);
  svg.setAttribute('viewBox', `0 0 ${width} ${height}`);
  svg.replaceChildren();

  // add one svg element with the given attributes and optional text
  function mark(tag, attributes, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', tag);
    for (const [key,value] of Object.entries(attributes)) node.setAttribute(key, value);
    if (text != null) node.textContent = text;
    svg.append(node);
  }

  // y axis title, grid lines and labels
  mark('text', {x:left, y:12}, 'Turnover / cycle');
  for (let i=0; i<4; i++) {
    const value = low+(high-low)*i/3;
    mark('line', {x1:left, x2:width-right, y1:y(value), y2:y(value), stroke:'#e9edf0'});
    mark('text', {x:left-8, y:y(value)+4, 'text-anchor':'end'}, value.toFixed(3));
  }

  // x axis grid lines and labels in mm, fewer on narrow screens
  let ticks = 5;
  if (width < 360) ticks = 2;
  for (let i=0; i<=ticks; i++) {
    const value = length*i/ticks;
    mark('line', {x1:x(value), x2:x(value), y1:top, y2:height-bottom, stroke:'#f0f2f4'});
    mark('text', {x:x(value), y:height-bottom+19, 'text-anchor':tickAnchor(i, ticks)}, Number(value.toPrecision(3)));
  }
  mark('text', {x:left+(width-left-right)/2, y:height-4, 'text-anchor':'middle'}, 'Channel position (mm)');

  // 0D mixed value as a dashed line and the 1D profile as a solid curve
  if (mixed != null) {
    mark('line', {x1:left, x2:width-right, y1:y(mixed), y2:y(mixed), stroke:'#708391', 'stroke-width':1.5,
      'stroke-dasharray':'5 4'});
  }
  const steps = [];
  for (let i = 0; i < xs.length; i++) {
    const command = i === 0 ? 'M' : 'L';
    steps.push(`${command}${x(xs[i]*MM_PER_M)},${y(ys[i])}`);
  }
  mark('path', {d:steps.join(' '), fill:'none', stroke:'#5aa9d6', 'stroke-width':2.3});
}

// show the displayed result: checks, output tables, profile and numerical attempts
function renderResult(origin='Saved output') {
  const record = displayed?.record;
  const models = record?.models || {};
  const hasModels = Boolean(models.mixed || models.spatial);
  byId('result-data').hidden = !hasModels;
  byId('empty-result').hidden = hasModels;
  if (record) byId('empty-result').textContent = 'No verified spatial result is available for this run.';
  else byId('empty-result').textContent = 'Choose a process and run a recipe, or open a saved result.';
  byId('result-origin').textContent = displayed ? `${origin} · ${displayed.id}` : 'No result selected';

  // status checks in the recipe panel
  byId('numerical').textContent = record?.status || '—';
  byId('numerical').className = record?.numerical_acceptance ? 'rx-pass' : 'rx-review';
  byId('feasible').textContent = labels[record?.recipe_feasibility] || '—';
  byId('feasible').className = record?.recipe_feasibility === 'pass' ? 'rx-pass' : 'rx-review';
  byId('grid').textContent = record?.accepted_cells ? `${record.accepted_cells} cells · verified` : 'Not verified';

  // output tables and notes
  byId('profile-panel').hidden = !record?.profile;
  fillRows('metrics', metricRows(models.mixed?.metrics, models.spatial?.metrics));
  byId('film-note').textContent = models.spatial?.metrics.film_status || '';
  byId('result-reason').hidden = !record?.reason;
  byId('result-reason').textContent = record?.reason || '';

  // numerical checks: each attempt plus the spatial diagnostics
  byId('attempt-panel').hidden = !record?.attempts?.length;
  const attempts = [];
  for (const row of record?.attempts || []) attempts.push([row.label, row.cells, row.status]);
  fillRows('attempts', attempts);
  const spatial = models.spatial?.metrics;
  let diagnostics = [];
  if (spatial) {
    diagnostics = [
      ['Relative turnover spread', number(spatial.relative_turnover_spread, 5)],
      ['A purge residual (scaled)', number(spatial.purge_a_residual, 5)],
      ['B purge residual (scaled)', number(spatial.purge_b_residual, 5)],
    ];
  }
  fillRows('diagnostics', diagnostics);
  showDraft();
  controls();
  drawChart();
}

// ---- saved runs ----

// load a saved run and display it, optionally taking over its inputs
async function openRun(name, adoptInputs=true, origin='Saved output') {
  selectionVersion += 1;
  const version = selectionVersion;
  const result = await api('/api/run/'+encodeURIComponent(name));
  if (version !== selectionVersion) return;
  displayed = result;
  if (adoptInputs) await setInputs(result.inputs);
  if (version !== selectionVersion) return;
  byId('saved-run').value = name;
  renderResult(origin);
}

// dropdown text for a saved run: process, start time and status
function runLabel(row) {
  const date = row.started_at ? new Date(row.started_at).toLocaleString() : row.id;
  return `${row.process_id} · ${date} · ${row.status}`;
}

// refill a run dropdown and keep the previous choice when it is still listed
function fillRunSelect(id, rows, placeholder) {
  const select = byId(id);
  const previous = select.value;
  select.replaceChildren(new Option(placeholder, ''));
  rows.forEach(row => select.add(new Option(runLabel(row), row.id)));
  if (rows.some(row => row.id === previous)) select.value = previous;
}

// fetch the saved run list and refill the saved run and compare dropdowns
async function refreshRuns() {
  savedRuns = await api('/api/runs');
  fillRunSelect('saved-run', savedRuns, savedRuns.length ? 'Choose saved run' : 'No saved runs');
  const ready = savedRuns.filter(row => row.ready);
  if (ready.length >= 2) byId('compare-empty').textContent = 'Choose two saved runs.';
  else byId('compare-empty').textContent = 'Complete two runs to compare their saved outputs.';
  fillRunSelect('compare-first', ready, 'Choose run');
  fillRunSelect('compare-second', ready, 'Choose run');
  if (displayed) byId('saved-run').value = displayed.id;
}

// ---- compare view ----

// compare the two chosen saved runs side by side
async function compareSelected() {
  const first = byId('compare-first').value;
  const second = byId('compare-second').value;
  byId('compare-empty').hidden = Boolean(first && second);
  byId('comparison-table').hidden = true;
  if (!first || !second) return;
  try {
    const result = await api('/api/compare', [first, second]);

    // ignore a response for an earlier selection.
    if (first !== byId('compare-first').value || second !== byId('compare-second').value) return;
    const [a,b] = result.runs;
    fillRows('comparison', [
      ['Process', a.process_name, b.process_name],
      ['Recipe (τ)', Object.values(a.recipe).join(' / '), Object.values(b.recipe).join(' / ')],
      ['Numerical', a.status, b.status],
      ['Recipe constraints', labels[a.recipe_feasibility], labels[b.recipe_feasibility]],
      ...metricRows(a.models?.spatial?.metrics, b.models?.spatial?.metrics),
    ]);
    byId('comparison-table').hidden = false;
  } catch (error) {
    if (first === byId('compare-first').value && second === byId('compare-second').value) errors([error.message]);
  }
}

// ---- views, downloads and job polling ----

// switch between the results, inputs and compare views
function setView(view) {
  document.querySelectorAll('[data-view]').forEach(button => {
    const selected = button.dataset.view === view;
    button.setAttribute('aria-pressed', String(selected));
    byId(button.dataset.view).hidden = !selected;
  });
  drawChart();
}

// save text to a file: through python in the desktop app, as a browser download otherwise
async function download(text, filename, type) {
  if (isDesktop) {
    try { await api('/api/desktop/export', {text, filename}); }
    catch (error) { errors([error.message]); }
    return;
  }
  const url = URL.createObjectURL(new Blob([text], {type}));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_LINK_MS);
}

// check the running job every second and open its result when it finishes
async function poll() {
  const version = jobVersion;
  try {
    const {active} = await api('/api/state');
    if (version !== jobVersion) return;
    connected = true;
    running = Boolean(active?.running);
    controls();
    if (active) {
      byId('status-text').textContent = active.record.stage || active.record.status;
      byId('stop').disabled = Boolean(active.stop_requested);
      if (running) activeId = active.id;
      else if (activeId === active.id) {
        // the watched job just finished: refresh the list and show its result
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
    connected = false;
    controls();
    byId('status-text').textContent = 'Workspace unavailable. Reconnecting…';
  } finally { setTimeout(poll, POLL_INTERVAL_MS); }
}

// ---- startup ----

// sidebar title for a process button
function processTitle(processInputs) {
  if (processInputs.id === 'synthetic-zno') return 'ZnO equivalent';
  if (processInputs.id === 'synthetic-ab') return 'Fictional A / B';
  return processInputs.name;
}

// sidebar subtitle for a process button
function processDetail(processInputs) {
  if (processInputs.id === 'synthetic-zno') return 'DEZ placeholder';
  return 'Synthetic';
}

// add one sidebar button per process; clicking it loads that process
function addProcessButtons() {
  const list = byId('process-list');
  for (const process of processes) {
    const button = document.createElement('button');
    button.className = 'rx-process';
    button.dataset.process = process.inputs.id;
    button.setAttribute('aria-pressed', 'false');
    const title = document.createElement('span');
    const detail = document.createElement('small');
    title.textContent = processTitle(process.inputs);
    detail.textContent = processDetail(process.inputs);
    title.append(detail);
    button.append(title);
    list.append(button);
    button.addEventListener('click', async () => {
      selectionVersion += 1;
      const selection = selectionVersion;
      try {
        displayed = null;
        byId('saved-run').value = '';
        await setInputs(process.inputs);
        renderResult();
        playSound('click');
        if (selection !== selectionVersion) return;
        // show the newest finished run of this process, if there is one
        const latest = savedRuns.find(row => row.process_id === process.inputs.id && row.ready);
        if (latest) await openRun(latest.id, false);
      } catch (error) { errors([error.message]); }
    });
  }
}

// load sounds, processes, saved runs and any running job, then start polling
async function initialize() {
  if (isDesktop) audioEnabled = await api('/api/desktop/sound');
  soundLabel();
  processes = await api('/api/processes');
  addProcessButtons();
  await refreshRuns();

  // resume a running job, otherwise start on the ZnO example (or the first process)
  const initial = await api('/api/state');
  running = Boolean(initial.active?.running);
  if (running) activeId = initial.active.id;
  if (running) await setInputs(initial.active.inputs);
  else await setInputs((processes.find(row => row.inputs.id === 'synthetic-zno') || processes[0]).inputs);

  // show the newest finished run of that process, if there is one
  const latest = savedRuns.find(row => row.process_id === inputs.id && row.ready);
  try {
    if (latest) await openRun(latest.id, false);
    else renderResult();
  } catch (error) {
    errors([error.message]);
    renderResult();
  }
  poll();
}

// ---- event handlers ----

// sounds on/off, saved in the desktop app and in browser storage
byId('sound-toggle').addEventListener('click', async () => {
  const previous = audioEnabled;
  byId('sound-toggle').disabled = true;
  audioEnabled = !audioEnabled;
  soundLabel();
  try {
    if (isDesktop) await api('/api/desktop/sound', audioEnabled);
    try { localStorage.setItem('ald-sounds', audioEnabled ? 'on' : 'off'); } catch (_) {}
  } catch (error) {
    audioEnabled = previous;
    soundLabel();
    errors([error.message]);
  } finally {
    byId('sound-toggle').disabled = false;
  }
  if (audioEnabled) playSound('click');
  else if (playingAudio) playingAudio.pause();
});

// view tabs
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  setView(button.dataset.view);
  playSound('click');
}));

// recipe edits: store the number and re-check shortly after typing stops
recipeFields.forEach(field => field.addEventListener('input', () => {
  if (!isJsonObject(inputs.recipe)) inputs.recipe = {};
  inputs.recipe[field.dataset.recipe] = field.value === '' ? null : Number(field.value);
  inspecting = true;
  inspectionVersion++;
  controls();
  showDraft();
  clearTimeout(inspectTimer);
  inspectTimer = setTimeout(inspectCurrent, INSPECT_DELAY_MS);
}));

// saved run dropdown
byId('saved-run').addEventListener('change', async event => {
  if (!event.target.value) return;
  try {
    await openRun(event.target.value);
    playSound('click');
  } catch (error) { errors([error.message]); }
});

// compare dropdowns
['compare-first','compare-second'].forEach(id => byId(id).addEventListener('change', compareSelected));

// open an inputs JSON file
byId('open-inputs').addEventListener('click', () => byId('input-file').click());
byId('input-file').addEventListener('change', async event => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    if (file.size > MAX_INPUT_BYTES) throw new Error('Input file must be at most 512 KB');
    const data = JSON.parse(await file.text());
    if (!isJsonObject(data)) throw new Error('Inputs must be a JSON object');
    selectionVersion++;
    displayed = null;
    byId('saved-run').value = '';
    await setInputs(data);
    renderResult();
    setView('inputs');
    playSound('click');
  } catch (error) { errors([error.message]); }
  event.target.value = '';
});

// save the current inputs as JSON
byId('save-inputs').addEventListener('click', () => {
  if (inputs) download(JSON.stringify(inputs, null, 2)+'\n', 'process-inputs.json', 'application/json');
});

// save the markdown report of the displayed run
byId('report').addEventListener('click', async () => {
  const name = displayed.id;
  try {
    const response = await fetch('/api/report/'+encodeURIComponent(name), {headers:{'X-Workspace-Token':token}});
    if (!response.ok) {
      const problem = await response.json();
      throw new Error(problem.error);
    }
    download(await response.text(), name+'-report.md', 'text/markdown');
  } catch (error) { errors([error.message]); }
});

// start a calculation with the current inputs
byId('run').addEventListener('click', async () => {
  jobVersion++;
  selectionVersion++;
  starting = true;
  controls();
  errors([]);
  try {
    const {active} = await api('/api/start', inputs);
    running = true;
    activeId = active.id;
    setView('results');
    byId('status-text').textContent = 'Starting solver';
    playSound('crystal');
  } catch (error) { errors([error.message]); }
  finally {
    jobVersion++;
    starting = false;
    controls();
  }
});

// ask python to stop the running calculation
byId('stop').addEventListener('click', async () => {
  byId('stop').disabled = true;
  try {
    await api('/api/stop', {});
    byId('status-text').textContent = 'Stopping; retaining completed attempts';
  } catch (error) {
    errors([error.message]);
    byId('stop').disabled = false;
  }
});

// redraw the chart when its size changes, then load the workspace
new ResizeObserver(drawChart).observe(byId('chart'));
initialize().catch(error => {
  errors([error.message]);
  byId('status-text').textContent = 'Could not load workspace';
});
