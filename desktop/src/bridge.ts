import { invoke } from "@tauri-apps/api/core";
export function request<T>(
  action: string,
  data: Record<string, unknown> = {},
): Promise<T> {
  return invoke<T>("desktop_action", { request: { action, ...data } });
}
const errors: Record<string, string> = {
  DIRECTORY_DIALOG_UNAVAILABLE: "暂时无法打开文件夹选择窗口，请重试或填写完整路径。",
  FILESYSTEM_PATH_REQUIRED: "请选择完整的文件夹路径。",
  INVALID_PUBLISHED_DIRECTORY: "请选择有效的完整保存路径。",
  PATH_PERMISSION_DENIED: "没有权限读写所选位置，请检查该文件夹或共享盘的权限。",
  PATH_UNAVAILABLE: "所选位置无法访问，请检查磁盘或共享连接。",
  PATH_ALREADY_EXISTS: "目标文件已存在，原文件已保留。",
  PATH_TYPE_CONFLICT: "目标位置存在同名文件夹或文件链接，请检查后重试。",
  BACKUP_STORE_IDENTITY_CONFLICT: "目录中的备份标识不匹配，已有文件未被覆盖。",
  HOST_IO_UNAVAILABLE: "读写未完成，请检查剩余空间、文件占用和连接状态。",
  INVALID_DIRECTORY_TARGET: "请选择报价表或报价图片的保存位置。",
  INVALID_ANALYTICS_QUERY: "请检查图表分组和起止时间。",
  ANALYTICS_RANGE_TOO_LARGE: "时间范围过大，请缩小范围或改用周、月、年分组。",
  ANALYTICS_NOT_SUPPORTED: "当前服务尚未提供利润汇总，请联系管理员更新服务。",

  OUTPUT_CJK_FONT_UNAVAILABLE: "报价图片所需中文字体不可用，请联系管理员。订单已保留。",
  DEPLOYMENT_NOT_CONFIGURED:"尚未配置，请联系管理员。",
  DEVICE_NOT_AUTHORIZED:"此设备授权已失效，请联系管理员。",
  DEVICE_PROFILE_MISMATCH:"此设备配置不匹配，请联系管理员。",
  DELIVERY_ROLE_MISMATCH:"此版本与设备授权不匹配，请联系管理员。",
  DEVICE_PROTOCOL_CONFLICT:"服务版本不兼容，请联系管理员更新。",
  MANUAL_LOGIN_DISABLED:"此版本使用自动连接。",

  UNAUTHENTICATED: "连接身份已失效，请重新连接。",
  ADMIN_REQUIRED: "此操作需要管理员权限。",
  NOT_FOUND: "订单不存在或当前账号无权查看。",
  SERVICE_UNREACHABLE_OR_CERTIFICATE_REJECTED:
    "无法连接服务，或服务证书未通过核验。请重试或联系管理员。",
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
    "待核查请求属于另一身份或服务，请恢复原身份和连接后核查。",
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
