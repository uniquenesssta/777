import test from 'node:test';
import assert from 'node:assert/strict';
import {backupReceipt,backupState} from '../src/features/settings/backupPresentation';
test('pending, failed and unverified backup results stay silent',()=>{
 assert.equal(backupReceipt({delivery_complete:false}),'');
 assert.equal(backupState({delivery_complete:false,last_success:{}}),'');
 assert.equal(backupState({delivery_complete:false,delivery_state:'failed'}),'');
 assert.equal(backupReceipt({}),'');
 assert.equal(backupState({last_success:{}}),'');
 assert.equal(backupState(null),'');
 assert.equal(backupState({delivery_complete:true,last_success:{},last_error:'offline'}),'');
});
test('only confirmed full delivery has a visible success',()=>{
 assert.equal(backupReceipt({delivery_complete:true}),'业务数据备份已完成。');
 assert.equal(backupState({delivery_complete:true,last_success:{}}),'备份正常');
});
