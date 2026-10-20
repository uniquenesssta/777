import {expect, type Page, type APIRequestContext} from '@playwright/test';
import {connectDevelopment} from '../../development-connection.mjs';
export const nativeHost='http://127.0.0.1:18777';
export async function nativeClient(page:Page,request:APIRequestContext) {
  const reset=await request.post(nativeHost+'/reset',{data:{}});
  expect(reset.ok()).toBe(true);
  const fixture=await reset.json();
  await page.addInitScript(()=>{
    (window as any).__TAURI_INTERNALS__={invoke:async(cmd:string,args:any)=>{
      if(cmd!=='desktop_action')return 0;
      const r=await fetch('http://127.0.0.1:18777/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(args.request)});
      const v=await r.json();if(v.error)throw v.error;return v.ok;
    }};
  });
  await page.goto('/');await connectDevelopment(page,fixture);
  return fixture;
}
export const nativeAction=(page:Page,action:Record<string,unknown>)=>page.evaluate(action=>(window as any).__TAURI_INTERNALS__.invoke('desktop_action',{request:action}),action);
