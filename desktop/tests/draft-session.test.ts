import {test} from 'node:test';
import assert from 'node:assert/strict';
import {startDraftSession,draftKey} from '../src/state/draftSession.ts';
const store=()=>{const data=new Map<string,string>();return {get length(){return data.size;},key:(i:number)=>[...data.keys()][i]??null,getItem:(k:string)=>data.get(k)??null,setItem:(k:string,v:string)=>{data.set(k,v);},removeItem:(k:string)=>{data.delete(k);},clear:()=>data.clear()};};
test('drafts survive page reload in one native run but never a new runtime, including old source drafts',()=>{
  const session=store(),legacy=store();
  legacy.setItem(draftKey,'old');legacy.setItem('unrelated-preference','keep');
  assert.equal(startDraftSession(session,legacy,'run-1'),null);
  session.setItem(draftKey,'current');session.setItem('777-desktop-draft-source-a','source');
  assert.equal(startDraftSession(session,legacy,'run-1'),'current');
  assert.equal(startDraftSession(session,legacy,'run-2'),null);
  assert.equal(session.getItem('777-desktop-draft-source-a'),null);
  assert.equal(legacy.getItem(draftKey),null);assert.equal(legacy.getItem('unrelated-preference'),'keep');
});
