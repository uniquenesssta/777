// Browser UI regression only: no installer build or Windows acceptance.
import {test, expect} from '@playwright/test';
import {orderRecords} from './fixtures/order-records-bridge';

test('detail and all actions fit without page or card scrolling', async ({page}, info) => {
  await orderRecords(page, 'development');
  await expect(page.getByRole('columnheader', {name:'创建人', exact:true})).toHaveCount(0);
  await page.evaluate(() => {
    const api=(window as any).__TAURI_INTERNALS__, original=api.invoke;
    api.invoke=async (command:string, args:any) => {
      const result=await original(command,args);
      if(args?.request?.action==='order') return {...result,
        lines:Array.from({length:25}, (_,i)=>({raw:{line_kind:'normal',product_id:`商品 ${i+1}`},normalized:{q:'1',sale:'10',k:'1'},income_cents:'1000'})),
        notes:[{note_id:'last',body:'最后一条备注',created_at:'2026-10-20T00:00:00Z'}],
        history:[{revision:'1',created_at:'2026-10-20T00:00:00Z'}]};
      return result;
    };
  });
  await page.getByRole('button',{name:'查看详情'}).first().click();
  for (const [width,height] of [[1440,852],[1440,1200],[1366,600],[1024,768],[720,600],[640,480]]) {
    await page.setViewportSize({width,height});
    for(const selector of ['.workspace','.order-detail','.order-detail .quote-card','.order-detail .settlement']) {
      expect(await page.locator(selector).evaluate(el=>el.scrollHeight<=el.clientHeight+1), `${selector} at ${width}x${height}`).toBe(true);
    }
    for(const name of ['返回订单记录','继续编辑','内部财务报表']) {
      await expect(page.getByRole('button',{name,exact:true})).toBeInViewport({ratio:1});
    }
    await expect(page.getByRole('button',{name:'备注记录（1）',exact:true})).toBeInViewport({ratio:1});
    const list=page.getByRole('region',{name:'商品明细滚动区'});
    await list.evaluate(el=>el.scrollTop=el.scrollHeight);
    await expect(list.getByText('商品 25',{exact:true})).toBeInViewport();
    await list.evaluate(el=>el.scrollTop=0);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    if(width===1440 && height===852 || width===640) await page.screenshot({path:info.outputPath(`detail-${width}-${height}.png`)});
  }
  await page.getByRole('button',{name:'备注记录（1）',exact:true}).click();
  await expect(page.getByRole('dialog')).toContainText('最后一条备注');
  await page.keyboard.press('Escape');
  await page.getByRole('button',{name:'修改记录（1）',exact:true}).click();
  await page.getByRole('dialog').locator('summary').click();
  await expect(page.getByRole('dialog')).toContainText('本次保存未改变客户信息');

});

for (const delivery of ['manager','sales','development']) {
  test(`${delivery} export controls follow delivery context`, async ({page}) => {
    // UI delivery context only; this does not prepare or verify a package.
    // Grant exports even for sales to check delivery hiding independently of permission.
    await orderRecords(page, delivery, false, delivery==='sales'?['quote','orders','exports']:undefined);
    await page.getByRole('button',{name:'查看详情'}).first().click();
    for (const name of ['导出报价','报价图片','内部财务报表']) {
      await expect(page.getByRole('button',{name,exact:true})).toHaveCount(delivery==='development'?1:0);
    }
    {
      await page.getByRole('button',{name:'导出记录',exact:true}).click();
      await expect(page.getByRole('button',{name:'导出 Excel',exact:true})).toHaveCount(delivery==='development'?1:0);
      await expect(page.getByRole('button',{name:'打开文件夹'})).toHaveCount(3);
      await page.evaluate(()=>(window as any).__jobCount=0);
      await page.getByRole('button',{name:'刷新',exact:true}).click();
      if(delivery!=='development') await expect(page.locator('.tasks-card')).not.toContainText('可在');
    }
  });
}
