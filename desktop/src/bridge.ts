import { showError } from "./state/formalPresentation";
import { invoke } from "@tauri-apps/api/core";
export function request<T>(
  action: string,
  data: Record<string, unknown> = {},
): Promise<T> {
  return invoke<T>("desktop_action", { request: { action, ...data } });
}
const errors: Record<string, string> = {
  LOCAL_SIGNER_UNAVAILABLE:"本机签发身份暂不可用，请检查开发日志；无需连接服务器授权。",
  LOCAL_ISSUER_STATE_INVALID:"本机签发身份文件无法读取，现有文件已保留，请检查开发日志。",
  PACKAGE_LEGACY_REBUILD_REQUIRED:"这是旧封包流程的未完成任务，请按当前版本与功能选择重新封包。",
  ISSUER_NOT_READY:"尚未获得 4.23 的封包授权，请先完成封包授权。",
  ISSUER_PAIR_UNREACHABLE_OR_CERTIFICATE_REJECTED:"尚未连接上 4.23 的临时授权服务（8478），或升级包证书不匹配。请确认 4.23 已运行本机生成的同一份 upgrade.cmd，且仍在等待连接；恢复后重试，无需重新生成。",
  ISSUER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED:"已读取主机身份，但未能连接或验证 4.23 的正式服务（8477）。请确认后台正在运行，恢复连接后重试；现有准备记录已保留。",
  CLUSTER_PRIMARY_UNREACHABLE_OR_CERTIFICATE_REJECTED:"未能连接或验证业务后台，请确认网络和服务状态，恢复后重试。",
  ISSUER_NATIVE_UNAVAILABLE:"未找到本机授权工具。请退出开发版后使用 npm run dev 重新启动，完成工具准备。",
  ISSUER_STATUS_UNAVAILABLE:"暂时无法读取本机封包授权状态。请刷新重试，现有准备记录不会被替换。",
  ISSUER_KIT_UNAVAILABLE:"原升级包已移动或丢失。请展开“更换升级包”重新生成，并在 4.23 运行新包。",
  WINDOWS_PACKAGING_REQUIRED:"请在 Windows 开发版中进行封包。",
  ISSUER_INTERFACE_SELECTION_REQUIRED:"请选择用于连接主机的本机网络接口。",
  PACKAGE_RESUME_CONFLICT:"本次任务的封包内容已经变化，请按当前选择重新封包。",
  UPGRADE_BINDING_CONFLICT:"4.23 与本机的升级材料不匹配。请在 4.23 运行本机的同一份升级包；若材料已过期，再展开“更换升级包”。",
  CONNECTION_FILE_INVALID: "文件内容不完整或格式不正确，请重新选择部署生成的文件。",
  CONNECTION_FILE_WRONG_KIND: "文件用途不匹配。Host 加入文件、公开连接文件和桌面登记文件不能混用。",
  CONNECTION_FILE_UNAVAILABLE: "无法读取所选文件，请检查位置和访问权限。",
  HOST_IDENTITY_UNAVAILABLE: "此服务未提供可核对的账本身份，请检查 Host 同步配置或服务版本。",
  INVALID_DIRECTORY_PREFERENCE: "位置中包含不支持的字符，或路径过长。",
  PACKAGE_TARGET_REQUIRED: "请先选择并核对正式封包目标。",
  PACKAGE_TARGET_REVERIFY: "请重新验证封包目标的管理员身份。目标已保留。",
  PACKAGE_TARGET_IDENTITY_MISMATCH: "目标账本身份发生变化，已阻止封包，请重新核对。",
  PACKAGE_LOOPBACK_FORBIDDEN: "正式封包不能使用 localhost 或本机回环地址，请导入正式 Host 连接。",
  PACKAGE_CONNECTION_MISMATCH: "登记文件与本安装包的服务目标不一致，请管理员核对后重新提供。",
  OUTPUT_SINGLE_ORDER_TOO_LARGE: "单笔订单已超过单个报表容量，无法继续按完整订单拆分。请检查该订单的明细或过长备注；本次未创建部分报表。",
  OUTPUT_SNAPSHOT_TOO_LARGE: "所选报表数据量过大，请缩小日期范围后分批导出。",
  OUTPUT_TOO_LARGE: "生成文件过大，请缩小日期范围后分批导出。",
  CUSTOMER_SELECTION_REQUIRED:"找到已有客户，请在匹配结果中选择该客户，再保存独立订单。",
  CUSTOMER_IDENTITY_CONFLICT:"淘宝 ID 与微信号对应的信息不一致，请重新选择客户或修正填写信息。",
  CUSTOMER_ORDER_NUMBER_EXISTS:"该客户已存在此订单号，请继续编辑原订单，或填写不同订单号。",
  OUTPUT_FOLDER_ON_HOST: "文件保存在服务主机本地，请在该主机打开；当前电脑无法直接访问此位置。",
  OUTPUT_FOLDER_UNAVAILABLE: "无法打开该次导出的文件夹，请检查共享连接、目录是否存在及访问权限。",
  OUTPUT_LOCATION_UNAVAILABLE: "这条导出记录没有可用的文件位置。",
  OUTPUT_NOT_READY: "文件尚未生成完成，请稍后再打开。",
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
  DEPLOYMENT_NOT_CONFIGURED:"请选择管理员提供的设备登记文件。",
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
  if (!showError(code)) return "";
  return errors[code] ?? `操作未完成（${code}）。请核对输入或重新读取。`;
}
