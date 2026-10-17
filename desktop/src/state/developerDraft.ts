import { restorableDraft } from './draft';
type DraftStore = Pick<Storage,'getItem'|'setItem'>;
export function selectDraftSource(store:DraftStore, previous:string|null, pin:string) {
  const key='777-desktop-draft-v1';
  const raw=store.getItem(key);
  let next=raw;
  if(previous && previous!==pin) {
    if(raw)store.setItem(`777-desktop-draft-source-${previous}`,raw);
    next=store.getItem(`777-desktop-draft-source-${pin}`);
  }
  const restored=restorableDraft(next);
  store.setItem(key,JSON.stringify({schema:key,source_pin:pin,details:restored.details,lines:restored.lines,editing:restored.editing,customer:restored.customer}));
  return next;
}
