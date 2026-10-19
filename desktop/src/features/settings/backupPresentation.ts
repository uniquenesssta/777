// Public, aggregate backup results. Hidden paths and internal error codes stay in logs.
export function backupState(value:Record<string,unknown>|null){
  if(value?.last_error||value?.error||value?.status==='unavailable'||value?.delivery_state==='failed')return '最近备份未完成';
  if(value?.delivery_complete===false)return '部分交付待完成';
  if(value?.last_success)return value.delivery_complete===true?'备份正常':'最近备份已生成';
  return '尚无备份';
}
export function backupReceipt(value:Record<string,unknown>){
  return value.delivery_complete===false?'业务数据备份已生成，部分交付待完成。':value.delivery_complete===true?'业务数据备份已完成。':'业务数据备份已生成。';
}
