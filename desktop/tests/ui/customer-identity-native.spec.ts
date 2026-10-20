import {test,expect} from '@playwright/test';
import {nativeClient,nativeAction,nativeHost} from './fixtures/native-client';
test.afterEach(async({request})=>{expect((await request.post(nativeHost+'/cleanup',{data:{}})).ok()).toBe(true);});
test('quote identity excludes order numbers and field-crossed matches through real native and Host',async({page,request})=>{
  await nativeClient(page,request);
  await page.getByLabel('订单号',{exact:true}).fill('00000');
  await expect(page.getByRole('region',{name:'匹配客户与订单'})).toHaveCount(0);
  for(const [customer,wechat,total] of [['00000','',0],['wx','',0],['','客户0',0],['客户0','',1],['客户0','wx',25]] as const){
    const found=await nativeAction(page,{action:'customer_orders',query:'',offset:0,identity:{customer,wechat}});
    expect(found.total).toBe(total);
  }
  await page.getByLabel('客户 / 淘宝 ID',{exact:true}).fill('客户0');
  const region=page.getByRole('region',{name:'匹配客户与订单'});
  await expect(region.getByRole('button',{name:'该客户新建订单',exact:true})).toHaveCount(1);
  await expect(region).toContainText('是否是这个客户');
  await expect(region).toContainText('00000');
  await page.getByLabel('客户 / 淘宝 ID',{exact:true}).fill('全新客户');
  await expect(region.getByRole('button',{name:'该客户新建订单',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'＋ 添加商品',exact:true}).click();
  await page.getByLabel('第1行商品',{exact:true}).selectOption('安装服务');
  await page.getByRole('button',{name:'计算报价',exact:true}).click();
  await page.getByRole('button',{name:'核对并提交订单',exact:true}).click();
  await page.getByRole('button',{name:'确认提交',exact:true}).click();
  await expect(page.getByRole('button',{name:'追加备注',exact:true})).toBeVisible();
});
