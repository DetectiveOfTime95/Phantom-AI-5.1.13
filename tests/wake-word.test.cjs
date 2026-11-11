const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const htmlPath = path.join(__dirname, '..', 'electron', 'renderer', 'index.html');
const html = fs.readFileSync(htmlPath, 'utf8');
const marker = '/* ---------- always-on LOCAL voice activation: “Hey Phantom” ---------- */';
const start = html.indexOf(marker);
const end = html.indexOf("$('#x-wake').onclick", start);
assert(start >= 0 && end > start, 'Local wake-word module must remain present in the renderer.');

function createHarness() {
  const events = [];
  let timerId = 0;
  const context = {
    window: { phantom: { backendUrl: 'http://127.0.0.1:8770', localApiToken: 'test' } },
    Date,
    setTimeout: () => ++timerId,
    clearTimeout: () => {},
    setInterval: () => ++timerId,
    clearInterval: () => {},
    on: true,
    busy: false,
    awake: 0,
    st: (_state, label) => events.push(['status', label]),
    log: (message) => events.push(['log', message]),
    say: (message) => {
      events.push(['say', message]);
      context.busy = true;
      return Promise.resolve();
    },
    handle: (command) => {
      events.push(['command', command]);
      context.busy = true;
      return Promise.resolve();
    },
    $: () => ({ textContent: '', style: {} }),
  };
  vm.createContext(context);
  vm.runInContext(html.slice(start, end), context);
  return { context, events };
}

{
  const { context, events } = createHarness();
  context.acceptWakeCommand('Hey Phantom, turn on the office lights');
  assert(events.some(([kind, value]) => kind === 'command' && value === 'turn on the office lights'));
}

{
  const { context, events } = createHarness();
  context.acceptWakeCommand('Hey Phantom');
  assert(events.some(([kind, value]) => kind === 'say' && value.includes("I'm listening")));
  context.busy = false;
  events.length = 0;
  context.acceptWakeCommand('What is the weather?');
  assert(events.some(([kind, value]) => kind === 'command' && value === 'What is the weather?'));
}

{
  const { context, events } = createHarness();
  context.acceptWakeCommand('Hey');
  context.acceptWakeCommand('Phantom, start the timer');
  assert(events.some(([kind, value]) => kind === 'command' && value === 'start the timer'));
}

console.log('Wake-word tests passed (same utterance, follow-up prompt, split local-recognition results).');
