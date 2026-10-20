import test from 'node:test';
import assert from 'node:assert/strict';
import { navigationRole } from '../src/state/navigation';
import { allowed } from '../src/state/permissions';
test('installed navigation survives session loss without widening selected permissions',()=>{
  for(const delivery of ['manager','sales']) {
    const before=navigationRole(delivery,false,delivery==='manager'?'admin':'sales');
    const after=navigationRole(delivery,false);
    assert.equal(after,before);
    assert.equal(allowed(['quote','orders'],after,'orders'),true);
    assert.equal(allowed(['quote','orders'],after,'prices'),false);
    assert.equal(allowed(null,navigationRole('sales',false),'finance'),false);
  }
});
test('developer tools keep navigation without inventing a business session',()=>{
  assert.equal(navigationRole('development',true),'admin');
  assert.equal(navigationRole('development',false),undefined);
  assert.equal(navigationRole('development',false,'sales'),'sales');
});
