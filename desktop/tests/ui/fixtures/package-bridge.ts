import type { Page } from '@playwright/test';
export async function setup(page:Page,delivery:string,permissions:string[]|null=null,businessSession=true) {
  await page.addInitScript(({delivery,permissions,businessSession})=>{
    const connection={url:'https://192.168.4.38:8477',certificate_sha256:'a'.repeat(64),certificate_pem:'fixture'};
    const target={target:{connection,ledger_id:'fixture-ledger'},verified:true};
    const state={daily:{hidden_dir:'D:\\Hidden',daily_hour:23},root:'D:\\Dev',backup_dir:'D:\\Backup',ledger_id:'fixture-ledger',last_backup:null,connection,
      preferences:{output:'D:\\Packages',version:'0.1.0',runtime:'downloadBootstrapper'},job:null,issuer:{ready:true,phase:'ready',interfaces:['192.168.4.80']}};
    (window as any).__requests=[];
    Object.defineProperty(window,'__TAURI_INTERNALS__',{value:{metadata:{currentWindow:{label:'main'},currentWebview:{label:'main'}},transformCallback:()=>1,unregisterCallback:()=>{},
      invoke:async(command:string,{request:r}:{request:any})=>{
        if(command!=='desktop_action')return 0;
        (window as any).__requests.push(r);
        switch(r.action){
          case 'ui_diagnostic':return null;
          case 'connection':return{delivery,permissions,developer_tools:delivery==='development',automatic:true,pending:false,connection:delivery==='development'?connection:null};
          case 'bootstrap':return{delivery,automatic:true,session:businessSession?{role:delivery==='sales'?'sales':'admin',username:'fixture',subject:'fixture',pending:false}:null};
          case 'prices':return{price_version_id:'fixture',items:[{product_id:'商品',sale:'10',unit_sale:'10',k:'1',single:true}]};
          case 'settings':return{revision:'1',export_dir:'D:\\Excel',image_dir:'D:\\Images'};
          case 'backup_status':return (window as any).__backupState??{target:'',last_success:null};
          case 'orders':return {orders:[],offset:0,total:0,limit:20,view:''};
          case 'outputs':return {offset:0,total:(window as any).__jobCount===0?0:100,limit:100,jobs:Array.from({length:(window as any).__jobCount??3},(_,i)=>({job_id:`job-${i}`,order_id:'order',kind:'excel_admin',state:'done',filename:`quote-${i}.xlsx`,created_at:'2026-10-20T00:00:00Z'}))};
          case 'analytics':{
            const count=(window as any).__analysisOrders??0;
            const totals={order_count:count,income_cents:count?'10000':'0',cost_cents:count?'4000':'0',profit_cents:count?'6000':'0',margin:count?'60.0%':null};
            return {format:'777-profit-analysis-v1',timezone:'Asia/Shanghai',ledger_revision:'1',from:r.from,to:r.to,period:r.period,totals,unplaced_date_orders:0,buckets:count?[{start:'2026-10-20',totals}]:[]};
          }
          case 'backup':if((window as any).__backupError)throw{code:'DAILY_BACKUP_FAILED'};return (window as any).__backupReceipt??{backup_id:'fixture',delivery_complete:false};
          case 'business_directory':return{directory:'',applied:false,ledger_id:'fixture'};
          case 'developer':{
            const issuer=(window as any).__issuerState??state.issuer;
            if(r.request.op==='issuer_connect'&&(window as any).__issuerError)throw {code:(window as any).__issuerError};
            if(r.request.op.startsWith('issuer_'))return issuer;
            return {...state,issuer,preferences:{...state.preferences,output:(window as any).__packageOutput??state.preferences.output},job:(window as any).__packageJob??null};
          }
          case 'package_target':case 'use_current_package_target':return target;
          case 'import_connection':return{connection};
          case 'pick_directory':return{directory:'D:\\Selected'};
          default:throw{code:'SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED'};
        }
      }}});
  },{delivery,permissions,businessSession});
  await page.goto('/');
}
