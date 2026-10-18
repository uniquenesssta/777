import {useEffect,useState} from 'react';
import {Button} from '../../ui/components';
import {developer} from './usePackaging';
import {errorMessage} from '../../bridge';
import type {IssuerState} from './types';
export function IssuerPage({onReturn}:{onReturn:()=>void}){
  const [state,setState]=useState<IssuerState|null>(null),[peer,setPeer]=useState(''),[busy,setBusy]=useState(false),[error,setError]=useState('');
  async function action(op:string,restart=false){setBusy(true);setError('');try{setState(await developer<IssuerState>(op,op==='issuer_prepare'?{peer:peer||null,restart}:{}));}catch(e){setError(errorMessage(e));}finally{setBusy(false);}}
  useEffect(()=>{void action('issuer_status');},[]);
  return <section className="card package-panel" data-node-id={state?.ready?'116:2526':error?'118:2296':'116:2252'}>
    <h2>{state?.ready?'发行准备完成':'发行维护'}</h2>
    {state?.ready?<><p>已绑定正式站点，可直接选择版本和功能封包。</p><div className="package-actions"><Button onClick={onReturn}>返回应用封包</Button></div><details><summary>查看维护详情</summary><p>正式站点：192.168.4.23:8477</p><p>账本：{state.ledger_id}</p><p>凭据保存在本机保护存储中，不显示。</p></details></>:<>
      <p>正式站点 · 192.168.4.23:8477</p><p>发行准备：尚未完成</p>
      <p>1 生成专用主机升级包<br/>2 在原主机运行一次升级<br/>3 返回本机完成绑定</p>
      <small className="muted">保留原账本和配置；必要时由 Windows 请求系统授权。此流程只做一次。</small>
      {(state?.interfaces.length??0)>1&&<fieldset disabled={busy}><legend>选择本机网络接口</legend>{state!.interfaces.map(ip=><label className="package-interface" key={ip}><input type="radio" name="issuer-interface" checked={peer===ip} onChange={()=>setPeer(ip)}/>{ip}</label>)}</fieldset>}
      <div className="package-actions"><Button disabled={busy||!state||((state.interfaces.length>1)&&!peer)} onClick={()=>void action('issuer_prepare',!!error)}>{error?'重新准备升级包':state?.phase==='pending'?'打开主机升级包':'准备主机升级包'}</Button><Button variant="outline" disabled={busy||state?.phase!=='pending'} onClick={()=>void action('issuer_connect')}>检查准备结果</Button></div>
    </>}
    {error&&<p className="inline-error" role="alert">{error}</p>}
  </section>;
}
