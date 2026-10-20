import type { CustomerListing, CustomerGroup, Order } from '../contracts';

export function customerQueries(details: Order['details']): string[] {
  return [...new Set([details.customer, details.wechat, details.order_ref].map(v => v.trim()).filter(Boolean))];
}
export function mergeCustomerMatches(results: CustomerListing[]): CustomerListing & {has_more:boolean} {
  const groups = new Map<string, CustomerGroup>();
  for (const result of results) for (const group of result.groups) {
    const previous = groups.get(group.group_id);
    if (!previous) groups.set(group.group_id, group);
    else groups.set(group.group_id, {...previous, orders:[...new Map([...previous.orders, ...group.orders].map(order => [order.order_id,order])).values()]});
  }
  return {...results[0], groups:[...groups.values()], total:Math.max(groups.size,...results.map(r=>r.total)), offset:results[0]?.offset ?? 0, limit:results[0]?.limit ?? 20, has_more:results.some(r=>r.offset+r.limit<r.total)};
}
