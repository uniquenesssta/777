import { useEffect, useState } from 'react';
import type { Workbench } from '../state/useWorkbench';
import { showError } from '../state/formalPresentation';
import { Button, Modal } from '../ui/components';
const customerErrors = new Set(['CUSTOMER_SELECTION_REQUIRED','CUSTOMER_IDENTITY_CONFLICT','CUSTOMER_ORDER_NUMBER_EXISTS']);
const changedOrder = new Set(['ORDER_REVISION_CHANGED','REVISION_OR_PRICE_CONFLICT']);

export function SubmitRecovery({app,valid}:{app:Workbench;valid:boolean}) {
  const [open,setOpen]=useState(false);
  useEffect(()=>{
    setOpen(!!app.saveFailure && showError(app.saveFailure) && !customerErrors.has(app.saveFailure) && !app.pending);
  },[app.saveFailure,app.pending]);
  const reload=changedOrder.has(app.saveFailure) && !!app.draft.editing;
  return <Modal open={open} onOpenChange={value=>!app.busy&&setOpen(value)} title="提交未完成" description={app.feedback || '填写内容已保留，请选择下一步。'} compact>
    <div className="dialog-actions">
      <Button variant="outline" disabled={app.busy} onClick={()=>setOpen(false)}>返回修改</Button>
      {reload ? <Button disabled={app.busy||app.pending} onClick={()=>{setOpen(false);void app.beginEdit(app.draft.editing!.order_id);}}>读取最新订单</Button> : <>
        <Button variant="outline" disabled={app.busy||app.pending} onClick={()=>{setOpen(false);void app.calculate();}}>重新核价</Button>
        {valid && <Button disabled={app.busy||app.pending} onClick={()=>{setOpen(false);void app.submit();}}>再次提交</Button>}
      </>}
    </div>
  </Modal>;
}
