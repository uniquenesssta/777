import type {Order} from '../contracts';
export type CustomerIdentity = Pick<Order['details'],'customer'|'wechat'>;
export function customerIdentity(details:Order['details']):CustomerIdentity {
  return {customer:details.customer.trim(),wechat:details.wechat.trim()};
}
export function hasCustomerIdentity(identity:CustomerIdentity):boolean {
  return !!(identity.customer || identity.wechat);
}
