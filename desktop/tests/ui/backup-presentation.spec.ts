// Public backup presentation through a mocked bridge; no real Host or installer.
import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
test('mother shows partial delivery without internal paths, errors or log controls',async({page},info)=>{
 await setup(page,'manager',['quote','settings','backup']);
 await page.evaluate(()=>{(window as any).__backupState={target:'\\\\192.168.4.23\\共享\\backup',delivery_complete:false,delivery_state:'partial',last_success:{created_at:'2026-10-18T16:30:00Z'}};});
 await page.getByRole('button',{name:'存储与备份',exact:true}).click();
 const panel=page.locator('.backup-settings').filter({has:page.getByRole('heading',{name:'业务数据备份',exact:true})});
 await expect(panel).toContainText('部分交付待完成');
 await expect(panel).toContainText('Excel 按月分表');
 await panel.getByRole('button',{name:'生成今日备份',exact:true}).click();
 await expect(page.getByRole('alert')).toHaveCount(0);
 await expect(page.locator('body')).not.toContainText(/服务备份|维护备份|192\.168\.4\.23|HIDDEN_|日志|logs/);
 for(const width of [1440,720]){await page.setViewportSize({width,height:1000});await page.evaluate(()=>scrollTo(0,0));await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);await panel.screenshot({path:info.outputPath(`backup-${width}.png`)});}
});
for(const edition of ['manager','sales'])test(`${edition} without backup permission has no backup entry`,async({page})=>{
 await setup(page,edition,['quote','settings']);await page.getByRole('button',{name:'存储与备份',exact:true}).click();
 await expect(page.getByRole('heading',{name:'业务数据备份',exact:true})).toHaveCount(0);await expect(page.getByRole('button',{name:'生成今日备份',exact:true})).toHaveCount(0);
 const requests=await page.evaluate(()=>(window as any).__requests);expect(requests.some((r:any)=>r.action==='backup_status'||r.action==='backup')).toBe(false);
});
