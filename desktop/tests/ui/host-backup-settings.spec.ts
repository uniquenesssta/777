import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
async function screen(page:any) {
  await setup(page,'development');
  await page.addInitScript(()=>{
    const api=(window as any).__TAURI_INTERNALS__,original=api.invoke;
    let state={ledger_id:'fixture-host-ledger',revision:'r1',backup_dir:'D:\\Backup',hidden_dir:'\\\\192.168.4.23\\共享\\backup',daily_hour:23,timezone:'Asia/Shanghai'};
    api.invoke=async(command:string,args:any)=>{
      const r=args?.request;
      if(!r||!['host_backup_settings','save_host_backup_settings','host_backup_directories'].includes(r.action))return original(command,args);
      (window as any).__requests.push(r);
      if((window as any).__hostError)throw {code:(window as any).__hostError};
      if(r.action==='host_backup_settings')return {...state};
      if(r.action==='save_host_backup_settings'){
        if((window as any).__saveHostError)throw {code:'HOST_BACKUP_SETTINGS_CHANGED'};
        state={...state,backup_dir:r.backup_dir,daily_hour:r.daily_hour,revision:'r2'};return {...state};
      }
      return {path:r.path,parent:'D:\\',directories:r.path==='D:\\Backup'?['D:\\Backup\\Next']:[],roots:['C:\\','D:\\'],truncated:false};
    };
  });
  await page.goto('/');await page.getByRole('button',{name:'开发者工具',exact:true}).click();await page.getByRole('button',{name:'Host 设置',exact:true}).click();
}
test('developer chooses Host directory and time then saves and rereads without local launcher writes',async({page},info)=>{
  await screen(page);
  await expect(page.getByLabel('Host 普通备份目录')).toHaveValue('D:\\Backup');
  await page.getByLabel('Host 每日备份时间').selectOption('6');
  await page.getByRole('button',{name:'选择 Host 文件夹',exact:true}).click();
  await page.getByRole('button',{name:'Next',exact:true}).click();
  await page.getByRole('button',{name:'选择当前文件夹',exact:true}).click();
  await page.getByRole('button',{name:'应用到当前 Host',exact:true}).click();
  await expect(page.getByRole('status')).toHaveText('已应用，回读确认一致。');
  const calls=await page.evaluate(()=>(window as any).__requests);
  const save=calls.find((v:any)=>v.action==='save_host_backup_settings');
  expect(save).toMatchObject({ledger_id:'fixture-host-ledger',expected_revision:'r1',backup_dir:'D:\\Backup\\Next',daily_hour:6});
  expect(calls.at(-1).action).toBe('host_backup_settings');
  expect(calls.some((v:any)=>v.action==='developer'&&v.request.op==='daily_backup')).toBe(false);
  await page.screenshot({path:info.outputPath('host-backup-settings.png')});
  await page.setViewportSize({width:720,height:600});
  await expect(page.getByRole('button',{name:'应用到当前 Host',exact:true})).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
});
test('failed apply keeps choices and never shows success; old Host asks for upgrade',async({page})=>{
  await screen(page);await page.getByLabel('Host 每日备份时间').selectOption('8');
  await page.evaluate(()=>(window as any).__saveHostError=true);
  await page.getByRole('button',{name:'应用到当前 Host',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('Host 设置已经改变');
  await expect(page.getByLabel('Host 每日备份时间')).toHaveValue('8');await expect(page.getByRole('status')).toHaveCount(0);
  await page.evaluate(()=>(window as any).__hostError='NOT_FOUND');
  await page.getByRole('button',{name:'重新读取',exact:true}).click();
  await expect(page.getByRole('alert')).toContainText('请先更新 Host 程序');
  await expect(page.getByRole('button',{name:'应用到当前 Host',exact:true})).toHaveCount(0);
});
