// Guest code executes in QuickJS WebAssembly, never Node eval/vm/Function.
// Only JSON MCP requests cross the host boundary. No guest fs/process/network.
import { getQuickJS } from 'quickjs-emscripten';
import readline from 'node:readline';

const input = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
const lines = input[Symbol.asyncIterator]();
const send = value => process.stdout.write(JSON.stringify(value) + '\n');
const first = await lines.next();
if (first.done) process.exit(2);
const spec = JSON.parse(first.value);
if (typeof spec.code !== 'string' || Buffer.byteLength(spec.code) > 65536) throw Error('Invalid code');
const QuickJS = await getQuickJS();
const runtime = QuickJS.newRuntime();
runtime.setMemoryLimit(32 * 1024 * 1024);
runtime.setMaxStackSize(512 * 1024);
// Budget counts synchronous guest execution slices, excluding awaited MCP work.
let remainingMs = 2000;
let sliceStart = performance.now();
runtime.setInterruptHandler(() => performance.now() - sliceStart > remainingMs);
const vm = runtime.newContext();
const deferred = new Map();
let serial = 0, outcome = null, bridges = 0;
function boundedRun(action) {
  sliceStart = performance.now();
  try { return action(); }
  finally { remainingMs -= performance.now() - sliceStart; }
}
function bind(name, fn) {
  const handle = vm.newFunction(name, fn);
  vm.setProp(vm.global, name, handle);
  handle.dispose();
}
bind('__call', payload => {
  if (outcome) return vm.throwError('Program already finalized');
  const encoded = vm.getString(payload);
  if (Buffer.byteLength(encoded) > 262144) return vm.throwError('Arguments exceed 256 KiB');
  if (++bridges > 100) return vm.throwError('Program exceeds 100 MCP calls');
  const request = JSON.parse(encoded);
  const promise = vm.newPromise();
  const id = ++serial;
  deferred.set(id, promise);
  send({ type: 'call', id, ...request });
  return promise.handle;
});
bind('__done', value => {
  if (outcome) return;
  const encoded = vm.getString(value);
  if (Buffer.byteLength(encoded) > 8192) outcome = { type: 'error', error: 'FINAL_OUTPUT_LIMIT_8192_BYTES' };
  else outcome = { type: 'done', value: JSON.parse(encoded) };
});
bind('__failed', value => { outcome ??= { type: 'error', error: vm.getString(value).slice(0, 2000) }; });
const boot = `
(() => {
  const call = globalThis.__call;
  const done = globalThis.__done;
  const failed = globalThis.__failed;
  delete globalThis.__call; delete globalThis.__done; delete globalThis.__failed;
  const mcp = Object.freeze({call: async (server, tool, args = {}) => {
    const wire = await call(JSON.stringify({server, tool, arguments:args}));
    const reply = JSON.parse(wire);
    if (!reply.ok) throw new Error((reply.error || 'MCP_CALL_FAILED') + (reply.error_detail ? ': ' + reply.error_detail : ''));
    return reply;
  }});
  const tables = ${JSON.stringify(spec.tools)};
  const tools = Object.create(null);
  for (const [alias, entry] of Object.entries(tables)) {
    const methods = Object.create(null);
    for (const name of entry.names) methods[name] = args => mcp.call(entry.server, name, args);
    tools[alias] = Object.freeze(methods);
  }
  Object.freeze(tools);
  const assert = (test, message = 'assertion failed') => {if (!test) throw new Error(message);};
  // Async return value is the ONLY final payload; intermediates stay in guest.
  (async (tools, mcp, assert) => { "use strict";\n${spec.code}\n})(tools,mcp,assert)
    .then(value => done(JSON.stringify(value === undefined ? null : value)))
    .catch(error => failed(String(error)));
})();`;

try {
  const initial = boundedRun(() => vm.evalCode(boot, 'agent-program.js'));
  if (initial.error) {
    outcome = { type: 'error', error: String(vm.dump(initial.error)).slice(0, 2000) };
    initial.error.dispose();
  } else initial.value.dispose();
  while (!outcome) {
    const jobs = boundedRun(() => runtime.executePendingJobs());
    if (jobs.error) {
      outcome = { type: 'error', error: JSON.stringify(jobs.error.context.dump(jobs.error)).slice(0, 2000) };
      jobs.error.dispose();
      break;
    }
    if (outcome) break;
    if (!deferred.size) { outcome = { type: 'error', error: 'UNRESOLVED_PROMISE_WITHOUT_HOST_CALL' }; break; }
    const line = await lines.next();
    if (line.done) { outcome = { type: 'error', error: 'HOST_CLOSED' }; break; }
    if (Buffer.byteLength(line.value) > 8 * 1024 * 1024) throw Error('Host response too large');
    const reply = JSON.parse(line.value);
    const promise = deferred.get(reply.id);
    if (!promise) throw Error('Unbound host reply');
    deferred.delete(reply.id);
    const value = vm.newString(JSON.stringify(reply.result));
    promise.resolve(value);
    value.dispose();
    promise.dispose();
  }
  if (outcome?.type === 'done' && deferred.size) outcome = { type: 'error', error: 'UNAWAITED_HOST_CALLS' };
  send({ ...outcome, guest_cpu_ms: Math.round(2000 - remainingMs), sandbox: 'QuickJS-WASM' });
} catch (error) {
  send({ type: 'error', error: String(error).slice(0, 2000), sandbox: 'QuickJS-WASM' });
} finally {
  for (const promise of deferred.values()) promise.dispose();
  vm.dispose();
  runtime.dispose();
  input.close();
}
