import test from 'node:test';
import assert from 'node:assert/strict';
import {backupReceipt,backupState} from '../src/features/settings/backupPresentation';
test('partial or unverified receipts never claim all delivery succeeded',()=>{
 assert.equal(backupReceipt({delivery_complete:false}),'业务数据备份已生成，部分交付待完成。');
 assert.equal(backupState({delivery_complete:false,last_success:{}}),'部分交付待完成');
 assert.equal(backupState({delivery_complete:false,delivery_state:'failed'}),'最近备份未完成');
 assert.equal(backupReceipt({}),'业务数据备份已生成。');
 assert.equal(backupReceipt({delivery_complete:true}),'业务数据备份已完成。');
});
