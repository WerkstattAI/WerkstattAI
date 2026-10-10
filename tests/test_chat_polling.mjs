import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const source = readFileSync(new URL('../templates/_chat_polling_script.html', import.meta.url), 'utf8');

function fixture() {
  const context = vm.createContext({});
  vm.runInContext(source, context);
  const tasks = new Map();
  const f = {session: 'first', visible: true, busy: false, calls: [], updates: [], errors: [], fetch: async () => ({ok: true})};
  let id = 0;
  f.poller = context.createWorkshopPoller({
    getSession: () => f.session, isVisible: () => f.visible, isBusy: () => f.busy,
    fetchUpdates: (sid) => { f.calls.push(sid); return f.fetch(); },
    onUpdates: (data) => f.updates.push(data), onError: (error) => f.errors.push(error),
    schedule: (callback, delay) => { tasks.set(++id, {callback, delay}); return id; },
    unschedule: (timer) => tasks.delete(timer),
  });
  f.delay = () => [...tasks.values()][0]?.delay;
  f.tick = () => { const [key, task] = [...tasks.entries()][0]; tasks.delete(key); return task.callback(); };
  return f;
}

test('idle polling receives workshop updates and schedules regular reads', async () => {
  const f = fixture();
  f.poller.start();
  await f.tick();
  assert.deepEqual(f.calls, ['first']);
  assert.deepEqual(f.updates, [{ok: true}]);
  assert.equal(f.delay(), 10000);
  await f.tick();
  assert.equal(f.updates.length, 2);
});

test('hidden or busy chat avoids network reads and resumes on wake', async () => {
  const f = fixture();
  f.poller.start();
  f.visible = false;
  await f.tick();
  f.visible = true;
  f.busy = true;
  await f.tick();
  assert.equal(f.calls.length, 0);
  f.busy = false;
  f.poller.wake();
  await f.tick();
  assert.equal(f.calls.length, 1);
});

test('reset discards an old-session response and never overlaps requests', async () => {
  const f = fixture();
  let complete;
  f.fetch = () => new Promise(resolve => { complete = resolve; });
  f.poller.start();
  const pending = f.tick();
  f.session = 'second';
  f.poller.wake();
  await f.tick();
  assert.equal(f.calls.length, 1);
  complete({private: 'old conversation'});
  await pending;
  assert.equal(f.updates.length, 0);
  f.fetch = async () => ({newConversation: true});
  await f.tick();
  assert.deepEqual(f.calls, ['first', 'second']);
  assert.deepEqual(f.updates, [{newConversation: true}]);
});

test('stop prevents a late update and new reads', async () => {
  const f = fixture();
  let complete;
  f.fetch = () => new Promise(resolve => { complete = resolve; });
  f.poller.start();
  const pending = f.tick();
  f.poller.stop();
  complete({old: true});
  await pending;
  assert.equal(f.updates.length, 0);
  assert.equal(f.delay(), undefined);
});

test('rate-limit backoff honors Retry-After and recovers after success', async () => {
  const f = fixture();
  f.fetch = async () => { const error = new Error('rate limited'); error.retryAfter = 90000; throw error; };
  f.poller.start();
  await f.tick();
  assert.equal(f.delay(), 90000);
  assert.equal(f.errors.length, 1);
  f.fetch = async () => ({recovered: true});
  await f.tick();
  assert.equal(f.delay(), 10000);
  assert.equal(f.updates.length, 1);
});
