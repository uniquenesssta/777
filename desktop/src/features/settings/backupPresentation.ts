// Only confirmed full delivery may produce a visible result. Pending work stays silent.
export function backupState(value:Record<string,unknown>|null){
  if(value?.last_error||value?.error||value?.status==='unavailable'||value?.delivery_state==='failed')return '';
  return value?.delivery_complete===true&&value?.last_success?'备份正常':'';
}
export function backupReceipt(value:Record<string,unknown>){
  return value.delivery_complete===true?'业务数据备份已完成。':'';
}
