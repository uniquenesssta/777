import fs from 'node:fs';
export const permissionCatalog = JSON.parse(fs.readFileSync(new URL('../permissions.json', import.meta.url), 'utf8'));
export function packagePermissions(delivery, selected) {
  if (!['manager', 'sales'].includes(delivery)) throw Error('DELIVERY_REQUIRED');
  const available = permissionCatalog.filter(p => delivery === 'manager' || !p.admin);
  const values = selected ?? available.map(p => p.id);
  if (!Array.isArray(values) || new Set(values).size !== values.length ||
      values.some(id => !available.some(p => p.id === id)) ||
      available.some(p => p.required && !values.includes(p.id)) ||
      available.some(p => values.includes(p.id) && p.needs.some(id => !values.includes(id)))) {
    throw Error('PACKAGE_PERMISSIONS_INVALID');
  }
  return permissionCatalog.filter(p => values.includes(p.id)).map(p => p.id);
}
