import {useEffect,useState} from "react";
import {request,errorMessage} from "../../bridge";
import {Button,Input} from "../../ui/components";
type Locations={root:string;image_dir:string;export_dir:string;report_dir:string};
export function LocalOutputDirectory({disabled,finance}:{disabled:boolean;finance:boolean}) {
  const [value,setValue]=useState<Locations|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState("");
  useEffect(()=>{let active=true;request<Locations>("output_settings").then(v=>{if(active)setValue(v);},e=>{if(active)setError(errorMessage(e));});return()=>{active=false;};},[]);
  async function choose(){
    setBusy(true);setError("");
    try{
      const picked=await request<{directory:string|null}>("pick_directory",{target:"output_root"});
      if(picked.directory)setValue(await request<Locations>("save_output_root",{root:picked.directory}));
    }catch(e){setError(errorMessage(e));}finally{setBusy(false);}
  }
  return <section className="local-output-settings">
    <div className="field"><label htmlFor="local-output-root">导出文件保存位置</label>
      <div className="directory-choice"><Input id="local-output-root" readOnly value={value?.root??""} placeholder="选择本机保存文件夹"/>
        <Button variant="outline" disabled={disabled||busy} onClick={()=>void choose()}>选择文件夹</Button></div>
    </div>
    <p className="muted">仅用于当前电脑，选择后自动保存。</p>
    <dl className="local-output-folders">
      {[['报价图片','PIC',value?.image_dir],['报价表','Excel',value?.export_dir],['内部财务报表','内部财务报表',value?.report_dir]].filter(([label])=>finance||label!=='内部财务报表').map(([label,folder,path])=><div key={folder}><dt>{label}</dt><dd title={path}>{path||folder}</dd></div>)}
    </dl>
    {error&&<p role="alert">{error}</p>}
  </section>;
}
