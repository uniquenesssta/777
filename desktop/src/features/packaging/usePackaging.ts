import {useEffect,useRef,useState} from 'react';
import {request,errorMessage} from '../../bridge';
import type {PackageConfiguration} from './types';
export const developer=<T,>(op:string,values:Record<string,unknown>={})=>request<T>('developer',{request:{op,...values}});
export function usePackaging(){
  const [state,setState]=useState<PackageConfiguration|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const locked=useRef(false),live=useRef(true);
  useEffect(()=>{live.current=true;const refresh=()=>{if(!locked.current)void developer<PackageConfiguration>('package_status').then(v=>{if(live.current)setState(v);}).catch(e=>{if(live.current)setError(errorMessage(e));});};refresh();const timer=setInterval(refresh,2500);return()=>{live.current=false;clearInterval(timer);};},[]);
  async function run<T>(work:()=>Promise<T>){if(locked.current)return;locked.current=true;setBusy(true);setError('');try{return await work();}catch(e){if(live.current)setError(errorMessage(e));}finally{locked.current=false;if(live.current)setBusy(false);}}
  const building=state?.job?.state==='running'||state?.job?.state==='cancelling';
  return {state,busy,error,building,run,setState};
}
