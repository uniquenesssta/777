import { useRef, useState } from 'react';
import type { PointerEvent, KeyboardEvent } from 'react';
import type { DraftLine } from '../state/draft';
import { moveLine } from '../state/reorder';

export function useLineReorder(lines: DraftLine[], change: (lines: DraftLine[]) => void, disabled: boolean) {
  const dragging = useRef<{id:string;x:number;y:number;target:number}|null>(null);
  const [target, setTarget] = useState<string | null>(null);
  const [announcement, announce] = useState('');
  const move = (id: string, index: number) => {
    if (disabled) return;
    const next = moveLine(lines, id, index);
    if (next !== lines) { change(next); announce(`已移至第${index + 1}行，请重新计算报价。`); }
  };
  const end = () => { dragging.current = null; setTarget(null); };
  const pointerMove = (event: PointerEvent<HTMLButtonElement>) => {
    const active=dragging.current;
    if (!active || disabled || Math.hypot(event.clientX-active.x,event.clientY-active.y)<5) return;
    const row=document.elementFromPoint(event.clientX,event.clientY)?.closest<HTMLElement>('[data-line-id]');
    const index=lines.findIndex(l=>l.id===row?.dataset.lineId);
    if(index>=0){active.target=index;setTarget(lines[index].id);}
    const scroll=event.currentTarget.closest('.line-scroll');
    if(scroll){const bounds=scroll.getBoundingClientRect();if(event.clientY<bounds.top+48)scroll.scrollTop-=20;if(event.clientY>bounds.bottom-48)scroll.scrollTop+=20;}
  };
  return {
    announcement,
    row: (id: string, _index: number) => ({'data-drop-target': target === id,'data-line-id':id}),
    // Pointer capture works inside Windows WebView even when the native file-drop
    // handler owns HTML drag events. Inputs and selection remain unaffected.
    handle: (id: string, index: number) => <button type="button" className="line-drag-handle"
      aria-label={`移动第${index + 1}行`} title="拖动调整顺序，也可按上下方向键移动" disabled={disabled}
      onPointerDown={event=>{if(event.button!==0||disabled)return;event.currentTarget.focus();event.currentTarget.setPointerCapture(event.pointerId);dragging.current={id,x:event.clientX,y:event.clientY,target:index};}}
      onPointerMove={pointerMove}
      onPointerUp={event=>{const active=dragging.current;if(active)move(active.id,active.target);end();if(event.currentTarget.hasPointerCapture(event.pointerId))event.currentTarget.releasePointerCapture(event.pointerId);}}
      onPointerCancel={end} onLostPointerCapture={end}
      onKeyDown={(event: KeyboardEvent) => {
        if (event.key !== 'ArrowUp' && event.key !== 'ArrowDown') return;
        event.preventDefault();move(id, index + (event.key === 'ArrowUp' ? -1 : 1));
      }}><span aria-hidden="true">⠿</span><small aria-hidden="true">{String(index + 1).padStart(2, '0')}</small></button>,
  };
}
