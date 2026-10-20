// Display availability comes from the installed role/permissions, never network reachability.
// This does not grant native authorization or invent an authenticated business session.
export function navigationRole(delivery: string, developerTools: boolean, sessionRole?: string): string | undefined {
  if (delivery === 'manager') return 'admin';
  if (delivery === 'sales') return 'sales';
  if (delivery === 'development' && developerTools) return 'admin';
  return sessionRole;
}
