import {test,expect} from '@playwright/test';
import {nativeClient,nativeAction,nativeHost} from './fixtures/native-client';
test.afterEach(async({request})=>{expect((await request.post(nativeHost+'/cleanup',{data:{}})).ok()).toBe(true);});
test('native IPC and live HTTPS Host apply destination/time, schedule backup and survive restart',async({page,request})=>{
  await nativeClient(page,request);
  const initial=await nativeAction(page,{action:'host_backup_settings'});
  const current=await nativeAction(page,{action:'host_backup_directories',ledger_id:initial.ledger_id,path:initial.backup_dir});
  const siblings=await nativeAction(page,{action:'host_backup_directories',ledger_id:initial.ledger_id,path:current.parent});
  const destination=siblings.directories.find((p:string)=>/[\\/]public$/.test(p));expect(destination).toBeTruthy();
  const save={action:'save_host_backup_settings',ledger_id:initial.ledger_id,expected_revision:initial.revision,backup_dir:destination,daily_hour:0};
  const applied=await nativeAction(page,save);expect(applied.backup_dir).toBe(destination);expect(applied.hidden_dir).toBe(initial.hidden_dir);
  expect(await nativeAction(page,save)).toEqual(applied);
  await expect.poll(async()=>{const status=await nativeAction(page,{action:'backup_status'});expect(status.target).toBe(destination);expect(status.plan.daily_hour).toBe(0);return status.last_success?.backup_id;},{timeout:15000}).toBeTruthy();
  const receipt=(await nativeAction(page,{action:'backup_status'})).last_success.backup_id;
  expect((await request.post(nativeHost+'/restart',{data:{}})).ok()).toBe(true);
  expect(await nativeAction(page,{action:'host_backup_settings'})).toEqual(applied);
  expect((await nativeAction(page,{action:'backup_status'})).last_success.backup_id).toBe(receipt);
});
