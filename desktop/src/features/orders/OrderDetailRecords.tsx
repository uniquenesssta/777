import {useState} from "react";
import type {Order} from "../../contracts";
import {stamp} from "../../state/format";
import {Button, Modal} from "../../ui/components";
import {OrderHistory} from "../OrderHistory";

export function OrderDetailRecords({order}:{order:Order}) {
  const [view,setView]=useState<"history"|"notes"|null>(null);
  return <>
    <footer className="detail-record-actions">
      <Button variant="ghost" onClick={()=>setView("history")}>修改记录（{order.history?.length??0}）</Button>
      <Button variant="ghost" onClick={()=>setView("notes")}>备注记录（{order.notes.length}）</Button>
    </footer>
    <Modal open={view!==null} onOpenChange={open=>!open&&setView(null)} title={view==="history"?"修改记录":"备注记录"}>
      {view==="history" ? order.history?.length ? <OrderHistory order={order}/> : <p className="muted">暂无修改记录</p> :
        <section className="note-history">
          {order.notes.length ? order.notes.map(note=><div key={note.note_id}><p>{note.body}</p><small>{stamp(note.created_at)}</small></div>) : <p className="muted">暂无备注</p>}
        </section>}
    </Modal>
  </>;
}
