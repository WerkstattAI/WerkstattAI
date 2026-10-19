import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source = readFileSync(new URL('../templates/_dashboard_live_script.html', import.meta.url),'utf8');
function fixture() {
  const ctx = vm.createContext({}); vm.runInContext(source,ctx);
  const tasks = new Map(); let id=0;
  const f={visible:true, calls:[], pages:[], errors:[], fetch:async after=>({cursor:after+1,events:[],more:false})};
  f.feed=ctx.createOwnerFeed({cursor:41, visible:()=>f.visible,
    fetchPage:cursor=>{f.calls.push(cursor);return f.fetch(cursor);},
    onPage:page=>f.pages.push(page),onError:error=>f.errors.push(error),
    schedule:(callback,ms)=>{tasks.set(++id,{callback,ms});return id;},cancel:key=>tasks.delete(key)});
  f.tick=()=>{const [key,t]=[...tasks.entries()][0];tasks.delete(key);return t.callback();};
  f.delay=()=>[...tasks.values()][0]?.ms;
  return f;
}
test('owner feed advances only after a successful page and polls every 15 seconds',async()=>{
  const f=fixture();f.feed.start();await f.tick();await f.tick();assert.deepEqual(f.calls,[41,42]);assert.equal(f.delay(),15000);
});
test('hidden tabs and overlapping callbacks never issue parallel requests',async()=>{
  const f=fixture();f.feed.start();f.visible=false;await f.tick();assert.equal(f.calls.length,0);
  f.visible=true;let finish;f.fetch=()=>new Promise(resolve=>finish=resolve);f.feed.wake();const pending=f.tick();f.feed.wake();
  assert.equal(f.delay(),undefined);finish({cursor:42,events:[]});await pending;assert.equal(f.calls.length,1);
});
test('network failure keeps cursor and honors retry-after without discarding work',async()=>{
  const f=fixture();f.fetch=async()=>{throw Object.assign(new Error('offline'),{retryAfter:90000});};
  f.feed.start();await f.tick();assert.equal(f.delay(),90000);assert.equal(f.pages.length,0);
  f.fetch=async()=>({cursor:42,events:[]});await f.tick();assert.deepEqual(f.calls,[41,41]);assert.equal(f.delay(),15000);
});
test('event backlog drains in bounded pages and stop discards a late result',async()=>{
  const f=fixture();f.fetch=async()=>({cursor:91,events:[],more:true});f.feed.start();await f.tick();assert.equal(f.delay(),2000);
  let finish;f.fetch=()=>new Promise(resolve=>finish=resolve);const pending=f.tick();f.feed.stop();finish({cursor:92,events:[]});await pending;
  assert.equal(f.pages.length,1);assert.equal(f.delay(),undefined);
});
test('rendering failure does not consume unseen events',async()=>{
  const f=fixture();f.pages.push=()=>{throw new Error('render failed');};f.feed.start();await f.tick();await f.tick();assert.deepEqual(f.calls,[41,41]);
});
