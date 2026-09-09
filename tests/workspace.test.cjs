/* Run with node --test tests/workspace.test.cjs; no browser packages needed. */
const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

function workspace(desktop=false) {
  const elements = new Map(), requests = [];
  function element(id) {
    if (!elements.has(id)) elements.set(id, {
      value:'', hidden:false, handlers:{}, dataset:{},
      addEventListener(event, handler) { this.handlers[event] = handler; },
      replaceChildren() {}, append() {}, setAttribute() {},
    });
    return elements.get(id);
  }
  const context = vm.createContext({
    document:{getElementById:element, querySelector:query => ({content:query.includes('desktop') && desktop ? 'true' : 'false'}),
      querySelectorAll:() => [], createElement:() => element('temporary')},
    localStorage:{getItem:() => null}, structuredClone,
    ResizeObserver:class { observe() {} }, setTimeout:() => 0, clearTimeout() {},
    fetch(url) {
      return new Promise(resolve => requests.push({url, resolve}));
    },
  });
  const source = fs.readFileSync(path.join(__dirname, '../src/ald_twin/ui/workspace.js'), 'utf8');
  vm.runInContext(source, context);
  // Startup's catalog request stays pending; tests exercise the actual handlers.
  requests.shift();
  return {element, requests, run:code => vm.runInContext(code, context)};
}

function respond(request, data) {
  request.resolve({ok:true, json:async () => data, text:async () => data});
}

test('comparison hides old values while a new selection is pending', async () => {
  const ui = workspace();
  ui.element('compare-first').value = 'first';
  ui.element('compare-second').value = 'second';
  const pending = ui.run('compareSelected()');
  assert.equal(ui.element('comparison-table').hidden, true);
  ui.element('compare-second').value = 'third';
  respond(ui.requests.shift(), {runs:[]});
  await pending;
  assert.equal(ui.element('comparison-table').hidden, true);
});

test('report keeps the requested run name after selection changes', async () => {
  const ui = workspace();
  ui.run("displayed = {id:'first'}; download = (text, name) => { exported = {text, name}; }");
  const pending = ui.element('report').handlers.click();
  assert.equal(ui.requests[0].url, '/api/report/first');
  ui.run("displayed = {id:'second'}");
  respond(ui.requests.shift(), 'first report');
  await pending;
  assert.equal(ui.run('exported.name'), 'first-report.md');
  assert.equal(ui.run('exported.text'), 'first report');
});

test('an earlier idle poll cannot clear a newly started job', async () => {
  const ui = workspace();
  const pending = ui.run('poll()');
  ui.run("jobVersion++; running = true; activeId = 'new'");
  respond(ui.requests.shift(), {active:null});
  await pending;
  assert.equal(ui.run('running'), true);
  assert.equal(ui.run('activeId'), 'new');
});

test('a stale inspection cannot relabel a later selected result', async () => {
  const ui = workspace();
  ui.run('setInputs = () => new Promise(resolve => { finishInspection = resolve; })');
  const pending = ui.run("openRun('first')");
  respond(ui.requests.shift(), {id:'first', inputs:{}});
  await new Promise(resolve => setImmediate(resolve));
  ui.run("selectionVersion++; displayed = {id:'second'}");
  ui.element('saved-run').value = 'second';
  ui.run('finishInspection()');
  await pending;
  assert.equal(ui.element('saved-run').value, 'second');
  assert.equal(ui.run('displayed.id'), 'second');
});

test('completion cannot restore old inputs after the user changes selection', async () => {
  const ui = workspace();
  ui.run("activeId = 'finished'; refreshRuns = () => new Promise(resolve => { finishRefresh = resolve; }); openRun = () => { opened = true; }; opened = false");
  const pending = ui.run('poll()');
  respond(ui.requests.shift(), {active:{id:'finished', running:false, ready:true, record:{stage:'Complete'}}});
  await new Promise(resolve => setImmediate(resolve));
  ui.run('selectionVersion++; finishRefresh()');
  await pending;
  assert.equal(ui.run('opened'), false);
});

test('starting a job invalidates an in-flight saved-result selection', () => {
  const ui = workspace();
  const before = ui.run('selectionVersion');
  ui.element('run').handlers.click();
  assert.equal(ui.run('selectionVersion'), before + 1);
  assert.equal(ui.requests[0].url, '/api/start');
});

test('desktop sound saves are serialized and a failed save restores the toggle', async () => {
  const ui = workspace(true);
  const pending = ui.element('sound-toggle').handlers.click();
  assert.equal(ui.element('sound-toggle').disabled, true);
  ui.requests.shift().resolve({ok:false, json:async () => ({error:'Cannot save preferences'})});
  await pending;
  assert.equal(ui.element('sound-toggle').disabled, false);
  assert.equal(ui.run('audioEnabled'), false);
  assert.equal(ui.element('sound-toggle').textContent, 'Sounds off');
});
