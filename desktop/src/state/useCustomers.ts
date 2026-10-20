import { useEffect, useState } from "react";
import type { CustomerListing } from "../contracts";
import type { Workbench } from "./useWorkbench";
import { errorMessage } from "../bridge";
import { mergeCustomerMatches } from "./customerMatches";
export function useCustomers(app:Workbench,query:string|string[],offset:number,group?:string,orderOffset=0,enabled=true,refresh=0,delay=0){
  const [data,setData]=useState<(CustomerListing & {has_more?:boolean})|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(false);
  useEffect(()=>{let alive=true;setData(null);setError("");if(!enabled){setLoading(false);return;}
    setLoading(true);const timer=setTimeout(()=>{(Array.isArray(query) ? Promise.all(query.map(q=>app.customerOrders(q,offset,group,orderOffset))).then(mergeCustomerMatches) : app.customerOrders(query,offset,group,orderOffset)).then(v=>{if(alive)setData(v);}).catch(e=>{if(alive)setError(errorMessage(e));}).finally(()=>{if(alive)setLoading(false);});},delay);
    return()=>{alive=false;clearTimeout(timer);};
  },[JSON.stringify(query),offset,group,orderOffset,enabled,refresh,delay,app.session?.subject,app.connection?.certificate_sha256]);
  return {data,error,loading};
}
