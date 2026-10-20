import {test,expect} from '@playwright/test';
import {orderRecords} from './fixtures/order-records-bridge';

test('all orders show both identities without sticky selection after detail return',async({page},info)=>{
  await orderRecords(page);
  const table=page.getByRole('table',{name:'全部订单',exact:true});
  await expect(table.locator('tbody tr')).toHaveCount(3);
  await expect(table.locator('tbody tr').nth(0)).toContainText('微信号：qinghe_demo');
  await expect(table.locator('tbody tr').nth(1)).toContainText('微信号：qinghe_store');
  await table.locator('tbody tr').nth(0).getByRole('button',{name:'查看详情'}).click();
  await page.getByRole('navigation').getByRole('button',{name:'订单记录',exact:true}).click();
  await page.mouse.move(0,0);
  await expect(table.locator('[data-selected=true]')).toHaveCount(0);
  const rows=await table.locator('tbody tr').evaluateAll(rows=>rows.map(row=>({background:getComputedStyle(row).backgroundColor,border:getComputedStyle(row.children[0]).borderBottomWidth})));
  expect(new Set(rows.map(row=>row.background)).size).toBe(1);
  expect(rows.every(row=>row.border==='1px')).toBe(true);
  await page.screenshot({path:info.outputPath('all-orders.png')});
});

test('same-name customers retain separate orders, paging and edit targets',async({page},info)=>{
  await orderRecords(page);
  await page.getByRole('button',{name:'按客户查看',exact:true}).click();
  const groups=page.locator('.customer-group');
  await expect(groups).toHaveCount(2);
  await expect(groups.nth(0).getByRole('heading')).toHaveText('青禾工作室');
  await expect(groups.nth(1).getByRole('heading')).toHaveText('青禾工作室');
  await expect(groups.nth(0)).toContainText('微信号：qinghe_demo');
  await expect(groups.nth(1)).toContainText('微信号：qinghe_store');
  await expect(groups.nth(0).getByRole('table').locator('tbody tr')).toHaveCount(2);
  await expect(groups.nth(1).getByRole('table').locator('tbody tr')).toHaveCount(1);
  await expect(groups.nth(0).getByRole('row').filter({hasText:'QH-3'}).getByRole('button',{name:'继续编辑'})).toHaveCount(0);
  await page.screenshot({path:info.outputPath('customer-groups.png')});
  await page.evaluate(() => {(window as any).__manyCustomerOrders=true;});
  await page.getByRole('button',{name:'查找',exact:true}).click();
  await expect(groups.nth(0).getByRole('table').locator('tbody tr')).toHaveCount(20);
  await groups.nth(0).getByRole('button',{name:'下一页订单'}).click();
  await expect(groups).toHaveCount(1);
  await expect(groups.first().getByRole('table').locator('tbody tr')).toHaveCount(1);
  await expect(groups.first().getByRole('table')).toContainText('QH-22');
  await expect(groups.first().getByRole('button',{name:'下一页订单'})).toBeDisabled();
  await expect.poll(()=>page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='customer_orders').at(-1))).toMatchObject({group_id:'customer-1',order_offset:20});
  await page.getByRole('button',{name:'返回客户列表'}).click();
  await expect(groups).toHaveCount(2);
  await groups.nth(1).getByRole('button',{name:'继续编辑',exact:true}).click();
  await expect(page.getByLabel('订单号',{exact:true})).toHaveValue('QH-2');
});

test('narrow window contains long identities and customer actions',async({page},info)=>{
  await page.setViewportSize({width:720,height:600});
  await orderRecords(page,'manager',true);
  await page.getByRole('button',{name:'按客户查看',exact:true}).click();
  const groups=page.locator('.customer-group');
  await expect(groups).toHaveCount(2);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  expect(await groups.first().evaluate(group=>group.scrollWidth<=group.clientWidth+1)).toBe(true);
  await expect(groups.first().getByRole('button',{name:'该客户新建订单'})).toBeVisible();
  await page.screenshot({path:info.outputPath('customer-groups-720.png')});
});

test('sales customer view retains edit and finance permission boundaries',async({page})=>{
  await orderRecords(page,'sales');
  await expect(page.getByRole('columnheader',{name:'利润（¥）'})).toHaveCount(0);
  await page.getByRole('button',{name:'按客户查看',exact:true}).click();
  await expect(page.locator('.customer-group')).toHaveCount(2);
  await expect(page.getByRole('button',{name:'继续编辑'})).toHaveCount(0);
  await expect(page.getByRole('heading',{name:'我的订单'})).toBeVisible();
});
