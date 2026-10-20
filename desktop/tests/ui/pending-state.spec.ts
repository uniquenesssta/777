import {test,expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';
test('definitively rejected retry clears the UI lock only after native journal confirmation',async({page})=>{
  await setup(page,'development');
  await page.evaluate(()=>{
    const api=(window as any).__TAURI_INTERNALS__,old=api.invoke;let pending=false;
    api.invoke=async(cmd:string,args:any)=>{
      const r=args?.request;
      if(r?.action==='delete_output'){pending=true;throw{code:'COMMIT_UNKNOWN',status:202};}
      if(r?.action==='recover'){if(!r.retry)return{pending:true,result:null};pending=false;throw{code:'NOT_FOUND',status:404};}
      const v=await old(cmd,args);
      if(r?.action==='connection')return{...v,pending};
      if(r?.action==='outputs')return{...v,jobs:v.jobs.slice(0,1).map((j:any)=>({...j,state:'failed'})),total:1};
      return v;
    };
  });
  await page.getByRole('navigation').getByRole('button',{name:'导出记录',exact:true}).click();
  await page.getByRole('button',{name:'删除记录',exact:true}).click();
  await page.getByRole('navigation').getByRole('button',{name:'报价工作台',exact:true}).click();
  await expect(page.getByRole('button',{name:'一键清除',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'核查原请求',exact:true}).click();
  await expect(page.getByRole('button',{name:'一键清除',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'按原请求重试',exact:true}).click();
  await expect(page.getByRole('button',{name:'一键清除',exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'核查原请求',exact:true})).toHaveCount(0);
});
