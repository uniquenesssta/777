// Real Rust IPC + HTTPS ledger reads; output bytes are generated on this computer.
import {test,expect} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import {execFileSync} from 'node:child_process';
import {nativeClient,nativeAction,nativeHost} from './fixtures/native-client';
test.afterEach(async({request})=>{await request.post(nativeHost+'/cleanup',{data:{}});});
test('all export formats save locally even when Host output directory is blocked',async({page,request},info)=>{
 const fixture=await nativeClient(page,request);
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'quote-exports-'));
 try{
  await nativeAction(page,{action:'save_output_root',root});
  expect(fs.readdirSync(root).sort()).toEqual(['Excel','PIC','内部财务报表'].sort());
  expect((await request.post(nativeHost+'/block-output-directory',{data:{}})).ok()).toBe(true);
  const listing=await nativeAction(page,{action:'orders',q:'',state:'',offset:0,view:''});
  const order=await nativeAction(page,{action:'order',order_id:listing.orders[0].order_id});
  const files:string[]=[];
  for(const [kind,folder] of [['excel_quote','Excel'],['quote_png','PIC'],['excel_admin','内部财务报表']]){
   const job=await nativeAction(page,{action:'create_output',kind,order_id:order.order_id,expected_revision:String(order.revision)});
   expect(job.state,JSON.stringify(job)).toBe('done');expect(path.dirname(job.local_path)).toBe(path.join(root,folder));expect(fs.statSync(job.local_path).size).toBeGreaterThan(100);files.push(job.local_path);
  }
  const jpg=fs.readFileSync(files[1]);expect(path.extname(files[1])).toBe('.jpg');expect(jpg.subarray(0,3)).toEqual(Buffer.from([255,216,255]));
  const decoded=JSON.parse(execFileSync('python',['-c',"from PIL import Image; import sys,json; im=Image.open(sys.argv[1]); im.load(); print(json.dumps([im.format,im.width,im.mode]))",files[1]],{encoding:'utf8'}));
  expect(decoded).toEqual(['JPEG',800,'L']);expect(jpg.length).toBeLessThan(27*1024);
  fs.copyFileSync(files[1],info.outputPath('quotation.jpg'));
  console.log(`Sample JPG: ${jpg.length} bytes`);
  await nativeAction(page,{action:'create_report',from:'2000-01-01',to:'2099-12-31'});
  let jobs=await nativeAction(page,{action:'outputs',offset:0});expect(jobs.total).toBe(4);expect(jobs.jobs.every((j:any)=>j.state==='done')).toBe(true);
  for(const job of jobs.jobs.filter((j:any)=>j.kind!=='excel_period')){expect(job.order_id).toBe(order.order_id);expect(job.order_ref).toBe(order.details.order_ref);}
  const report=jobs.jobs.find((j:any)=>j.kind==='excel_period');
  const xml=execFileSync('python',['-c',"import zipfile,sys; z=zipfile.ZipFile(sys.argv[1]); print('\\n'.join(z.read(n).decode('utf8') for n in z.namelist() if n.endswith('.xml')))",report.local_path],{encoding:'utf8'});
  expect(xml).toContain('客户0');expect(xml).toContain('客户24');
  // Changing the root affects future files, never moves old exports.
  const next=path.join(root,'next');await nativeAction(page,{action:'save_output_root',root:next});
  jobs=await nativeAction(page,{action:'outputs',offset:0});expect(jobs.jobs.find((j:any)=>j.kind==='quote_png').local_path).toBe(files[1]);
  await page.getByRole('navigation').getByRole('button',{name:'订单记录',exact:true}).click();
  await page.getByRole('button',{name:'查看详情',exact:true}).first().click();
  for(const name of ['导出报价','导出图片','内部财务报表']) {
   await page.getByRole('button',{name,exact:true}).click();
   await expect(page.getByRole('button',{name,exact:true})).toBeEnabled();
   await expect(page.locator('.order-detail')).toBeVisible();
   await expect(page.locator('.tasks-card')).toHaveCount(0);
  }
  await page.getByRole('navigation').getByRole('button',{name:'导出记录',exact:true}).click();
  await expect(page.getByRole('button',{name:order.details.order_ref,exact:true}).first()).toBeVisible();
  await page.getByRole('button',{name:order.details.order_ref,exact:true}).first().click();
  await expect(page.locator('.order-detail')).toContainText(order.details.order_ref);
  const hostRoot=path.dirname(fixture.profile);
  const inventory=execFileSync('python',['-c',"import pathlib,sqlite3,sys,json; rows=[]\nfor p in pathlib.Path(sys.argv[1]).rglob('*.sqlite3'):\n if 'desktop' in p.parts: continue\n try:\n  c=sqlite3.connect(str(p)); tables=[r[0] for r in c.execute(\"select name from sqlite_master where type='table'\")];\n  if 'jobs' in tables: rows.append(c.execute('select count(*) from jobs').fetchone()[0])\n except sqlite3.Error: pass\nprint(json.dumps(rows))",hostRoot],{encoding:'utf8'});
  expect(JSON.parse(inventory)).toEqual([0]);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
