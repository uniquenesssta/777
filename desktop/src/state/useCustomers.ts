import { useEffect, useState } from "react";
import type { CustomerListing } from "../contracts";
import type { Workbench } from "./useWorkbench";
import { errorMessage } from "../bridge";
import type {CustomerIdentity} from "./customerMatches";
export function useCustomers(app:Workbench,query:string|CustomerIdentity,offset:number,group?:string,orderOffset=0,enabled=true,refresh=0,delay=0){
  const [data,setData]=useState<(CustomerListing & {has_more?:boolean})|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(false);
  useEffect(()=>{let alive=true;setData(null);setError("");if(!enabled){setLoading(false);return;}
    setLoading(true);const timer=setTimeout(()=>{(typeof query === "string" ? app.customerOrders(query,offset,group,orderOffset) : app.customerMatches(query,offset)).then(v=>{if(alive)setData({...v,has_more:v.offset+v.limit<v.total});}).catch(e=>{if(alive)setError(errorMessage(e));}).finally(()=>{if(alive)setLoading(false);});},delay);
    return()=>{alive=false;clearTimeout(timer);};
  },[JSON.stringify(query),offset,group,orderOffset,enabled,refresh,delay,app.session?.subject,app.connection?.certificate_sha256]);
  return {data,error,loading};
}
