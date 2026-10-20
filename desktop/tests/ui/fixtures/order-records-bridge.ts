// UI-only data; real Rust order/edit/export coverage remains in workbench.spec.ts.
import type { Page } from '@playwright/test';
import { setup } from './package-bridge';
export async function orderRecords(page: Page, delivery = 'manager', longIdentity = false, permissions?: string[]) {
  await setup(page, delivery, permissions ?? (delivery === 'sales' ? ['quote', 'orders'] : null));
  await page.evaluate(({longIdentity}) => {
    const make = (index: number, group: number, state = 'active') => ({
      order_id: `order-${index}`, customer_id: `customer-${group}`, revision: '1', state,
      created_at: `2026-10-${String(20-(index%20)).padStart(2,'0')}T03:00:00Z`,
      details: {customer: longIdentity ? '同名客户淘宝名称'.repeat(12) : '青禾工作室', wechat: `${group === 1 ? 'qinghe_demo' : 'qinghe_store'}${longIdentity ? '_long_identity'.repeat(5) : ''}`, order_ref: `QH-${index}`},
      income_cents:'10000',cost_cents:'4000',profit_cents:'6000',lines:[],notes:[],price_version_id:'fixture',owner_id:'fixture',
    });
    const orders = [make(1,1),make(2,2),make(3,1,'void')];
    const api=(window as any).__TAURI_INTERNALS__, previous=api.invoke;
    api.invoke=async(command:string,args:any)=>{
      const r=args?.request;
      if(command!=='desktop_action')return previous(command,args);
      if(['orders','order','customer_orders','order_changes'].includes(r.action)){
        (window as any).__requests.push(r);
        if(r.action==='orders')return {orders,offset:0,total:3,limit:20,view:''};
        if(r.action==='order')return orders.find(order=>order.order_id===r.order_id);
        if(r.action==='order_changes')return {changes:[],history:[]};
        const source=(window as any).__manyCustomerOrders ? [...orders,...Array.from({length:19},(_,i)=>make(i+4,1))] : orders;
        const groups=[1,2].map(group=>{
          const all=source.filter(order=>order.customer_id===`customer-${group}`);
          const active=all.filter(order=>order.state==='active');
          return {group_id:`customer-${group}`,details:orders[group-1].details,orders:all.slice(r.order_offset??0,(r.order_offset??0)+20),
            total:all.length,active_count:active.length,totals:{income_cents:String(active.length*10000)},order_offset:r.order_offset??0};
        });
        const found=r.group_id?groups.filter(group=>group.group_id===r.group_id):groups;
        return {groups:found,total:found.length,offset:0,limit:20};
      }
      return previous(command,args);
    };
  },{longIdentity});
  await page.getByRole('navigation').getByRole('button',{name:delivery==='sales'?'我的订单':'订单记录',exact:true}).click();
}
