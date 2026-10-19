// Public backup presentation through a mocked bridge; no real Host or installer.
import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
for(const state of ['partial','failed','unknown'])test(`mother silently waits for ${state} backup`,async({page},info)=>{
 await setup(page,'manager',['quote','settings','backup']);
 await page.evaluate(state=>{
  (window as any).__backupState={target:'\\\\192.168.4.23\\共享\\backup',delivery_complete:state==='unknown'?undefined:false,delivery_state:state,last_success:{created_at:'2026-10-18T16:30:00Z'}};
  (window as any).__backupReceipt=state==='unknown'?{}:{delivery_complete:false};
  (window as any).__backupError=state==='failed';
 },state);
 await page.getByRole('button',{name:'存储与备份',exact:true}).click();
 const panel=page.locator('.business-backup');
 await expect(panel.locator('.backup-state')).toHaveCount(0);
 await expect(panel).toContainText('Excel 按月分表');
 await panel.getByRole('button',{name:'生成今日备份',exact:true}).click();
 await expect(page.getByRole('alert')).toHaveCount(0);
 await expect(panel.locator('.backup-state')).toHaveCount(0);
 await expect(page.locator('body')).not.toContainText(/部分交付|未完成|最近成功|备份正常|备份已|状态：|服务备份|维护备份|192\.168\.4\.23|HIDDEN_|日志|logs/);
 if(state==='partial')for(const width of [1440,720]){await page.setViewportSize({width,height:1000});await page.evaluate(()=>scrollTo(0,0));await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await panel.screenshot({path:info.outputPath(`backup-${width}.png`)});}
});
test('complete backup retains truthful business success',async({page})=>{
 await setup(page,'manager',['quote','settings','backup']);
 await page.evaluate(()=>{(window as any).__backupState={delivery_complete:true,delivery_state:'complete',last_success:{created_at:'2026-10-18T16:30:00Z'}};(window as any).__backupReceipt={delivery_complete:true};});
 await page.getByRole('button',{name:'存储与备份',exact:true}).click();
 await expect(page.locator('.backup-state')).toContainText('备份正常');
 await page.getByRole('button',{name:'生成今日备份',exact:true}).click();
 await expect(page.locator('.backup-state')).toContainText('备份正常');
 await expect(page.getByRole('alert')).toHaveCount(0);
});
for(const edition of ['manager','sales'])test(`${edition} without backup permission has no backup entry`,async({page})=>{
 await setup(page,edition,['quote','settings']);await page.getByRole('button',{name:'存储与备份',exact:true}).click();
 await expect(page.getByRole('heading',{name:'业务数据备份',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'生成今日备份',exact:true})).toHaveCount(0);
 const requests=await page.evaluate(()=>(window as any).__requests);expect(requests.some((r:any)=>r.action==='backup_status'||r.action==='backup')).toBe(false);
});
