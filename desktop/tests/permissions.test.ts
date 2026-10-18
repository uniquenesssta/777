import test from 'node:test';
import assert from 'node:assert/strict';
import { defaults, togglePermission, allowed } from '../src/state/permissions.ts';
import { packagePermissions } from '../tools/package-permissions.mjs';
import { setDeliveryContext } from '../src/state/formalPresentation.ts';
import { errorMessage } from '../src/bridge.ts';

test('both editions preserve dependencies through choices and packaging rejects hand-edited escalation',()=>{
  for(const delivery of ['manager','sales'] as const) {
    assert.deepEqual(packagePermissions(delivery,defaults(delivery)),defaults(delivery));
    for(const id of defaults(delivery)) assert.doesNotThrow(()=>packagePermissions(delivery,togglePermission(defaults(delivery),id,false)));
  }
  assert.throws(()=>packagePermissions('sales',['quote','finance']));
  assert.throws(()=>packagePermissions('manager',['quote','prices']));
  assert.throws(()=>packagePermissions('manager',['quote','orders','orders']));
  assert.throws(()=>packagePermissions('manager',['quote','admin']));
  assert.deepEqual(togglePermission(['quote'],'exports',true),['quote','orders','exports']);
  assert(!togglePermission(defaults('manager'),'finance',false).includes('prices'));
});
test('visibility intersects the package and authenticated role',()=>{
  assert.equal(allowed(['finance'],'sales','finance'),false);
  assert.equal(allowed(['quote'],'admin','finance'),false);
  assert.equal(allowed(['quote','orders'],'sales','orders'),true);
});
test('formal errors never expose service failures, codes or guessed messages',()=>{
  for(const delivery of ['manager','sales']) {
    setDeliveryContext(delivery);
    for(const code of ['UNAUTHENTICATED','DEPLOYMENT_NOT_CONFIGURED','DEVICE_NOT_AUTHORIZED','SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED','UNEXPECTED_ERROR'])
      assert.equal(errorMessage({code}), '');
    assert.match(errorMessage({code:'CUSTOMER_ORDER_NUMBER_EXISTS'}),/订单号/);
  }
  setDeliveryContext('development');
  assert.match(errorMessage({code:'UNAUTHENTICATED'}),/重新连接/);
});
