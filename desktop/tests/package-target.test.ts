import test from 'node:test';
import assert from 'node:assert/strict';
import { requireNetworkTarget } from '../tools/package-target.mjs';
test('formal targets reject normalized loopback addresses without building installers',()=>{
  for(const host of ['localhost','LOCALHOST.','x.localhost','127.0.0.1','127.4.5.6','127.1','0x7f000001','[::1]','[::ffff:127.0.0.1]','0.0.0.0','[::]']) {
    assert.throws(()=>requireNetworkTarget({url:`https://${host}:8477`}),/PACKAGE_LOOPBACK_FORBIDDEN/);
  }
  assert.equal(requireNetworkTarget({url:'https://192.168.4.23:8477'}).url,'https://192.168.4.23:8477');
});
