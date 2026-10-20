import test from 'node:test';
import assert from 'node:assert/strict';
import {priceVersionLabel} from '../src/state/priceVersion.ts';
test('price labels use Beijing publication date and persistent daily sequence',()=>{
  assert.equal(priceVersionLabel('2026-10-19T16:00:00+00:00','1'),'261020-1');
  assert.equal(priceVersionLabel('2026-10-20T15:59:59Z','12'),'261020-12');
  assert.equal(priceVersionLabel('2026-10-20T16:00:00Z','1'),'261021-1');
  assert.equal(priceVersionLabel('2026-10-20T08:30:00+08:00','2'),'261020-2');
  for(const [date,n] of [[undefined,'1'],['bad','1'],['2026-10-20T00:00:00','1'],['2026-10-20T00:00:00Z','0'],['2026-10-20T00:00:00Z',undefined]] as const)
    assert.equal(priceVersionLabel(date,n),null);
});
