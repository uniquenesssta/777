import test from 'node:test';
import assert from 'node:assert/strict';
import { selectDraftSource } from '../src/state/developerDraft.ts';
test('A to B to A preserves raw drafts without moving authority or drafts across ledgers',()=>{
  const values=new Map<string,string>();
  const store={getItem:(k:string)=>values.get(k)??null,setItem:(k:string,v:string)=>{values.set(k,v);}};
  const key='777-desktop-draft-v1';
  store.setItem(key,JSON.stringify({schema:key,source_pin:'a',details:{customer:'A',order_ref:'0001',wechat:''},lines:[],calculation:{income_cents:'99999'}}));
  assert.equal(selectDraftSource(store,'a','b'),null);
  assert.equal(JSON.parse(store.getItem(key)!).details.customer,'');
  store.setItem(key,JSON.stringify({schema:key,source_pin:'b',details:{customer:'B',order_ref:'0002',wechat:''},lines:[]}));
  selectDraftSource(store,'b','a');
  assert.equal(JSON.parse(store.getItem(key)!).details.customer,'A');
  assert.equal(JSON.parse(store.getItem(key)!).calculation,undefined);
  selectDraftSource(store,'a','b');
  assert.equal(JSON.parse(store.getItem(key)!).details.customer,'B');
});
test('unavailable local storage fails before replacing the current source record',()=>{
  const raw='{"schema":"777-desktop-draft-v1","source_pin":"a"}';
  const store={getItem:()=>raw,setItem:()=>{throw Error('quota');}};
  assert.throws(()=>selectDraftSource(store,'a','b'),/quota/);
  assert.equal(store.getItem(),raw);
});
