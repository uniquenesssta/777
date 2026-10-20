import {useEffect,useRef,useState} from 'react';
import {Button} from '../../ui/components';
import {developer} from './usePackaging';
import {errorMessage} from '../../bridge';
import type {IssuerState} from './types';
export function IssuerPage({onReturn}:{onReturn:()=>void}){
  const [state,setState]=useState<IssuerState|null>(null),[peer,setPeer]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState(''),[confirmRestart,setConfirmRestart]=useState(false);
  const locked=useRef(false);
  async function action(op:string,restart=false){
    if(locked.current)return;
    locked.current=true;setBusy(true);setError('');
    try{
      const next=await developer<IssuerState>(op,op==='issuer_prepare'?{peer:peer||null,restart}:{});
      setState(next);setConfirmRestart(false);
      if(next.error)setError(errorMessage({code:next.error}));
    }catch(e){setError(errorMessage(e));}
    finally{locked.current=false;setBusy(false);}
  }
  useEffect(()=>{void action('issuer_status');},[]);
  const pending=state?.phase==='pending';
  const unavailable=!state||state.phase==='unavailable'||state.phase==='windows_required';
  const choosePeer=(state?.interfaces.length??0)>1;
  return <section className="card package-panel issuer-panel" aria-busy={busy} data-node-id={state?.ready?'116:2526':error?'118:2296':'116:2252'}>
    <h2>{state?.ready?'已获得封包授权':'与 4.23 完成封包授权'}</h2>
    {state?.ready?<><p>已绑定正式站点，可直接选择版本和功能封包。</p><div className="package-actions"><Button onClick={onReturn}>返回应用封包</Button></div><details><summary>查看维护详情</summary><p>正式站点：192.168.4.23:8477</p><p>账本：{state.ledger_id}</p><p>凭据保存在本机保护存储中，不显示。</p></details></>:<>
      <p>让本机制作的安装包自动接入 4.23。连接业务数据与封包授权是两项独立操作。</p>
      <p className="issuer-status" role="status">{busy?'正在处理…':state?.phase==='windows_required'?'请在 Windows 开发版中完成封包授权。':pending?'已生成升级包，等待连接 4.23 完成授权。':unavailable?'尚未读取到封包授权状态。':'尚未准备主机升级包。'}</p>
      <ol className="issuer-steps"><li>在本机生成升级包。</li><li>将整个升级包带到 4.23，运行 <code>upgrade.cmd</code>。</li><li>返回本机，点击“连接 4.23 完成授权”。</li></ol>
      <small className="muted">升级保留原账本和配置。这是开发者的一次准备，正式端使用者无需操作。</small>
      {choosePeer&&(!pending||confirmRestart)&&<fieldset disabled={busy}><legend>选择本机连接 4.23 的局域网地址</legend>{state!.interfaces.map(ip=><label className="package-interface" key={ip}><input type="radio" name="issuer-interface" checked={peer===ip} onChange={()=>setPeer(ip)}/>{ip}</label>)}</fieldset>}
      <div className="package-actions">
        {pending?<><Button disabled={busy} onClick={()=>void action('issuer_connect')}>连接 4.23 完成授权</Button><Button variant="outline" disabled={busy} onClick={()=>void action('issuer_open')}>打开原升级包</Button></>:<Button disabled={busy||unavailable||(choosePeer&&!peer)} onClick={()=>void action('issuer_prepare')}>生成主机升级包</Button>}
        <Button variant="ghost" disabled={busy} onClick={()=>void action('issuer_status')}>刷新授权状态</Button>
      </div>
    </>}
    {error&&<p className="inline-error" role="alert">{error}</p>}
    {pending&&!state?.ready&&<details className="issuer-recovery"><summary>更换升级包</summary><p className="muted">仅在升级包过期、丢失或准备材料不匹配时使用。重新生成后，必须在 4.23 运行新包，再返回本机连接。</p>
      {confirmRestart?<div className="package-actions"><Button disabled={busy||(choosePeer&&!peer)} onClick={()=>void action('issuer_prepare',true)}>确认生成新升级包</Button><Button variant="ghost" disabled={busy} onClick={()=>setConfirmRestart(false)}>取消</Button></div>:<Button variant="outline" disabled={busy} onClick={()=>setConfirmRestart(true)}>重新生成升级包</Button>}
    </details>}
  </section>;
}
