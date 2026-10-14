import { invoke } from "@tauri-apps/api/core";
export function request<T>(
  action: string,
  data: Record<string, unknown> = {},
): Promise<T> {
  return invoke<T>("desktop_action", { request: { action, ...data } });
}
const errors: Record<string, string> = {
  UNAUTHENTICATED: "登录已失效，请重新登录。",
  ADMIN_REQUIRED: "此操作需要管理员权限。",
  NOT_FOUND: "订单不存在或当前账号无权查看。",
  SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED:
    "无法连接服务，或服务证书未通过核验。请检查连接设置。",
  CERTIFICATE_PIN_MISMATCH: "证书与填写的指纹不一致。",
  INVALID_CONNECTION: "请检查 HTTPS 地址、证书和 64 位小写指纹。",
  PRICE_VERSION_CHANGED: "价格版本已更新，请刷新价格、重新计算并核对。",
  PRICE_STALE: "价格版本已更新，请刷新价格、重新计算并核对。",
  ORDER_REVISION_CHANGED: "订单已有新变化，请重新读取详情。",
  REVISION_OR_PRICE_CONFLICT: "订单或价格已有变化，请刷新后核对。",
  QUERY_VIEW_CHANGED: "订单列表已有变化，请刷新列表。",
  SETTINGS_REVISION_CONFLICT: "目录设置已有变化，请重新读取后保存。",
  CALCULATION_REQUIRED: "请先计算并核对报价。",
  CALCULATION_STALE: "输入已经修改，请重新计算。",
  PENDING_REQUEST_REQUIRES_QUERY: "有结果未知的原请求，请先核查回执。",
  COMMIT_UNKNOWN: "请求结果未知，已保留原请求。请先核查，勿重复提交。",
  PENDING_IDENTITY_MISMATCH:
    "待核查请求属于另一账号或服务，请使用原账号和连接登录核查。",
  LOCAL_PENDING_UNAVAILABLE: "本机待核查记录不可读或不可保存，已停止发送。",
  PROTOCOL_VERSION_CONFLICT: "服务版本不兼容，请检查客户端与服务版本。",
  INVALID_LOGIN: "请填写有效的账号和密码。",
};
export function errorCode(e: unknown): string {
  return typeof e === "object" && e !== null && "code" in e
    ? String(e.code)
    : "UNEXPECTED_ERROR";
}
export function errorMessage(e: unknown): string {
  const code = errorCode(e);
  return errors[code] ?? `操作未完成（${code}）。请核对输入或重新读取。`;
}
