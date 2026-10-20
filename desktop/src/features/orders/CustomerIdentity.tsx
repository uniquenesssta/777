import type { Order } from "../../contracts";

export function CustomerIdentity({details, heading = false}: {details: Order["details"]; heading?: boolean}) {
  const name = details.customer || "未填写客户";
  return <div className="order-customer-identity">
    {heading && <small>客户 / 淘宝 ID</small>}
    {heading ? <h3>{name}</h3> : <strong>{name}</strong>}
    <small>微信号：{details.wechat || "未填写"}</small>
  </div>;
}
