import {useState} from 'react';
import {Button, Modal} from '../../ui/components';
import {errorMessage} from '../../bridge';
import {developer} from './usePackaging';
import type {PackageConfiguration} from './types';

export function PackageCleanup({disabled,onCleaned}:{disabled:boolean;onCleaned:(state:PackageConfiguration)=>void}) {
  const [plan,setPlan]=useState<{count:number;outputs:string[]}|null>(null);
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  async function preview(){setBusy(true);setError('');try{setPlan(await developer('package_cleanup_preview'));}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  async function clear(){setBusy(true);setError('');try{onCleaned(await developer('clear_packages'));setPlan(null);}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  return <div>
    <Button variant="outline" disabled={disabled||busy} onClick={()=>void preview()}>清除所有封包</Button>
    {!plan&&error&&<p role="alert">{error}</p>}
    <Modal className="package-cleanup-dialog" open={!!plan} onOpenChange={value=>!value&&!busy&&setPlan(null)} title="清除所有封包" description={`共 ${plan?.count??0} 个本机封包目录，将删除安装包及失败封包残留。业务数据、已安装程序和本机签发身份保留。`}>
      <div className="package-cleanup-list">{plan?.outputs.map(path=><p className="package-path" key={path}>{path}</p>)}</div>
      {plan?.count===0&&<p>没有可清理的封包。</p>}
      {error&&<p role="alert">{error}</p>}
      <div className="dialog-actions"><Button variant="outline" disabled={busy} onClick={()=>setPlan(null)}>取消</Button><Button variant="danger" disabled={busy||!plan?.count} onClick={()=>void clear()}>确认清除</Button></div>
    </Modal>
  </div>;
}
