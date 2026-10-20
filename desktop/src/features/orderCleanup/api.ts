import {request,errorCode,errorMessage} from '../../bridge';
export type CleanupOrder={order_id:string;revision:string|number;details:{customer:string;wechat:string;order_ref:string};income_cents:string;deleted_at?:string;deleted_by?:string;reason?:string};
export type CleanupPage={ledger_id:string;orders:CleanupOrder[];total:number;offset:number;limit:number};
export type DeleteChoice={ledger_id:string;request_id:string;order:CleanupOrder;reason:string};
export const readOrders=(query:string,offset:number,history:boolean)=>request<CleanupPage>('developer_orders',{query,offset,history});
export const removeOrder=(v:DeleteChoice)=>request('delete_order',{ledger_id:v.ledger_id,request_id:v.request_id,order_id:v.order.order_id,expected_revision:String(v.order.revision),reason:v.reason});
export function cleanupError(e:unknown){return ({SERVICE_RESPONSE_INCOMPLETE:'未收到完整的删除结果，可重试核查；不会重复删除。',SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED:'暂时无法连接后台，恢复连接后可重试原操作。',NOT_FOUND:'当前后台尚不支持订单清理，请先更新 Host。',ORDER_DELETE_LEDGER_CHANGED:'连接的账本已改变，请重新读取订单。',REVISION_OR_PRICE_CONFLICT:'订单已被修改，请重新读取后核对。',ORDER_DELETED:'此订单已删除，请重新读取列表。',CLUSTER_REPLICA_CANNOT_WRITE:'请连接主 Host 后清理订单。'} as Record<string,string>)[errorCode(e)]??errorMessage(e);}
