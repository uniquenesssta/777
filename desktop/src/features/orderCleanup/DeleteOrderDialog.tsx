import {errorCode} from '../../bridge';
import {useState} from 'react';
import {Button,Field,Input,Modal} from '../../ui/components';
import {money} from '../../state/format';
import {cleanupError,removeOrder,type DeleteChoice} from './api';
export function DeleteOrderDialog({choice,onClose,onDeleted}:{choice:DeleteChoice;onClose:()=>void;onDeleted:()=>void}){
 const [reason,setReason]=useState('');const [busy,setBusy]=useState(false);const [error,setError]=useState('');const [reload,setReload]=useState(false);const [submitted,setSubmitted]=useState<DeleteChoice|null>(null);
 async function submit(){if(busy||(!submitted&&!reason.trim()))return;const command=submitted??{...choice,reason:reason.trim()};setSubmitted(command);setBusy(true);setError('');try{await removeOrder(command);onDeleted();}catch(e){setError(cleanupError(e));setReload(['ORDER_DELETE_LEDGER_CHANGED','REVISION_OR_PRICE_CONFLICT','ORDER_DELETED'].includes(errorCode(e)));}finally{setBusy(false);}}
 return <Modal open onOpenChange={v=>{if(!v&&!busy)onClose();}} title="删除这笔订单？" compact>
  <div className="cleanup-confirm"><strong>{choice.order.details.customer||'未填写客户'} · {choice.order.details.order_ref||'未填写订单号'}</strong><span>微信：{choice.order.details.wechat||'—'} · 金额：{money(choice.order.income_cents)}</span><small>账本：{choice.ledger_id}</small><p>删除后不再显示在订单列表，也不计入统计。删除记录和历史备份保留；其他设备联网后同步。</p>
  <Field label="删除原因"><Input autoFocus maxLength={512} disabled={busy||!!submitted} value={reason} onChange={e=>setReason(e.target.value)} placeholder="例如：清理测试订单"/></Field>
  {error&&<p role="alert" className="inline-error">{error}</p>}
  <div className="cleanup-actions"><Button variant="outline" disabled={busy} onClick={onClose}>取消</Button><Button variant="danger" disabled={busy||!reason.trim()} onClick={()=>reload?onClose():void submit()}>{reload?'重新读取订单':busy?'正在删除':submitted?'重试删除':'确认删除'}</Button></div></div>
 </Modal>;
}
