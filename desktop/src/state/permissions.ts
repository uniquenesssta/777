import catalog from '../../permissions.json' with {type:'json'};
export const permissionCatalog = catalog;
export type Permission = 'quote'|'orders'|'edit_orders'|'finance'|'prices'|'exports'|'settings'|'backup';
export type Delivery = 'manager'|'sales';
export const defaults = (delivery: Delivery): string[] => catalog.filter(p => delivery === 'manager' || !p.admin).map(p => p.id);
export function togglePermission(selected: string[], id: string, checked: boolean): string[] {
  const next = new Set(selected);
  function add(key:string) { next.add(key); catalog.find(p=>p.id===key)?.needs.forEach(add); }
  function remove(key:string) { next.delete(key); catalog.filter(p=>p.needs.includes(key)).forEach(p=>remove(p.id)); }
  if (catalog.find(p=>p.id===id)?.required) return selected;
  if (checked) add(id); else remove(id);
  return catalog.filter(p=>next.has(p.id)).map(p=>p.id);
}
export function allowed(selected: string[]|null, role: string|undefined, id: Permission): boolean {
  const item = catalog.find(p=>p.id===id);
  return !!item && (!item.admin || role === 'admin') && (selected === null || selected.includes(id));
}
