import { request, errorCode, errorMessage } from '../../bridge';
export type HostBackup = { ledger_id:string; revision:string; backup_dir:string; hidden_dir:string; daily_hour:number; timezone:string };
export type HostDirectories = { path:string; parent:string|null; directories:string[]; roots:string[]; truncated:boolean };
export const readHostBackup = () => request<HostBackup>('host_backup_settings');
export const saveHostBackup = (current:HostBackup, backup_dir:string, daily_hour:number) =>
  request<HostBackup>('save_host_backup_settings',{ledger_id:current.ledger_id,expected_revision:current.revision,backup_dir,daily_hour});
export const browseHost = (ledger_id:string,path:string) => request<HostDirectories>('host_backup_directories',{ledger_id,path});
export function hostError(error:unknown):string {
  const labels:Record<string,string>={
    NOT_FOUND:'当前 Host 尚不支持远程备份设置，请先更新 Host 程序。',
    HOST_BACKUP_SETTINGS_CHANGED:'Host 设置已经改变，请重新读取后再选择。',
    HOST_BACKUP_LEDGER_CHANGED:'当前连接的账本已改变，请重新读取设置。',
    BACKUP_DIRECTORY_CONFLICT:'备份目录不能与业务数据或隐藏备份目录相同、互相包含。',
    CLUSTER_REPLICA_CANNOT_WRITE:'请连接负责业务数据的主 Host 后修改。',
    HOST_BACKUP_READBACK_MISMATCH:'回读结果与本次选择不同，请重新读取后确认。',
  };
  return labels[errorCode(error)]??errorMessage(error);
}
