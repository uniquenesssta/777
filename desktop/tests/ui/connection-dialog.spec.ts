import {test, expect} from '@playwright/test';
import {setup} from './fixtures/package-bridge';

for (const target of [false]) {
  test(`${target ? 'package target' : 'developer connection'} dialog contains controls at desktop and narrow sizes`, async ({page}, info) => {
    await setup(page, 'development');
    await page.getByRole('button', {name:'开发者工具', exact:true}).click();
    await page.getByRole('button', {name:'开发数据', exact:true}).click();
    await page.getByRole('button', {name:target?'核对或更换目标':'选择或更换后台连接', exact:true}).click();
    const dialog=page.getByRole('dialog');
    await expect(dialog).toHaveAccessibleName(target?'选择封包连接的后台':'连接后台服务');
    await expect(dialog.getByLabel('账号',{exact:true})).toHaveCount(0);
    await expect(dialog.locator('input[type=password]')).toHaveCount(0);
    await expect(dialog.locator('details')).not.toHaveAttribute('open', '');
    await dialog.getByRole('button', {name:'选择后台连接文件', exact:true}).click();
    await expect(dialog.getByLabel('服务地址', {exact:true})).toHaveValue('https://192.168.4.38:8477');
    await dialog.locator('summary').click();
    await dialog.getByRole('textbox', {name:'服务证书（PEM）', exact:true}).fill('-----BEGIN CERTIFICATE-----\n'+'A'.repeat(4096)+'\n-----END CERTIFICATE-----');
    await dialog.getByLabel('证书 SHA-256 指纹', {exact:true}).fill('a'.repeat(64));
    for(const viewport of [{width:1440,height:884},{width:720,height:600},{width:390,height:600}]) {
      await page.setViewportSize(viewport);
      const geometry=await dialog.evaluate(el=>{
        const box=el.getBoundingClientRect();
        const controls=Array.from(el.querySelectorAll('input, textarea, button'));
        return {inside:controls.every(control=>{const r=control.getBoundingClientRect();return r.left>=box.left+16&&r.right<=box.right-16;}),
          horizontalOverflow:el.scrollWidth>el.clientWidth+1, onScreen:box.top>=15&&box.bottom<=innerHeight-15};
      });
      expect(geometry).toEqual({inside:true,horizontalOverflow:false,onScreen:true});
      const submit=dialog.getByRole('button',{name:target?'核对并保存目标':'验证并连接',exact:true});
      await submit.scrollIntoViewIfNeeded();
      await expect(submit).toBeInViewport();
      if(viewport.width===1440)await page.screenshot({path:info.outputPath('dialog-expanded.png')});
    }
    await dialog.getByRole('button',{name:'取消',exact:true}).click();
    await expect(dialog).toHaveCount(0);
    expect(await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='connect'||r.action==='verify_package_target'))).toHaveLength(0);
  });
}

test('developer connection submits only public connection information',async({page})=>{
  await setup(page,'development');
  await page.getByRole('button',{name:'开发者工具',exact:true}).click();
  await page.getByRole('button',{name:'开发数据',exact:true}).click();
  await page.getByRole('button',{name:'选择或更换后台连接',exact:true}).click();
  await page.getByRole('dialog').getByRole('button',{name:'验证并连接',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='connect'))).toHaveLength(1);
  const [r]=await page.evaluate(()=>(window as any).__requests.filter((r:any)=>r.action==='connect'));
  expect(Object.keys(r).sort()).toEqual(['action','connection']);
});
