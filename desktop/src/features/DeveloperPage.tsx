import { useEffect, useRef, useState } from "react";
import { stamp } from "../state/format";
import { request, errorCode, errorMessage } from "../bridge";
import { Badge, Button, Field, Input, Modal } from "../ui/components";
import { type TargetState } from "./connection/PackageTarget";
import { permissionCatalog } from "../state/permissions";
import { PackageChoices } from "./connection/PackageChoices";
import type { Workbench } from "../state/useWorkbench";

type Job = { id:string; state:"running"|"cancelling"|"cancelled"|"failed"|"succeeded"; delivery:string; version:string; output:string; lines:string[]; error:string|null; bytes:number|null; source_commit?:string };
type Configuration = { source?:{original:string;working_copy:string}|null; daily:{hidden_dir:string;daily_hour:number}; daily_result?:{normal?:{ok:boolean};hidden?:{ok:boolean;error?:string}}; root:string; backup_dir:string; ledger_id:string; last_backup:{created_at?:string}|null; connection:{url:string;certificate_sha256:string}; preferences:{output:string; version:string; runtime:string}; job:Job|null };
const labels: Record<string,string> = {
  DATA_BACKUP_INVALID:"恢复文件格式不正确。",
  DATA_BACKUP_HASH_INVALID:"文件校验未通过，当前账本未改动。",
  DATA_BACKUP_VERSION_UNSUPPORTED:"此备份格式暂不支持，当前账本未改动。",
  RESTORE_REQUIRES_NEW_DIRECTORY:"请选择新的空目录，已有账本未改动。",
  DAILY_BACKUP_CONFIG_INVALID:"每日时间请输入 0 到 23 的整点小时。",
  DEVELOPER_LAUNCHER_REQUIRED:"请使用开发版启动命令打开软件，再进入开发部署。",
  FILESYSTEM_PATH_REQUIRED:"请选择完整的文件夹路径。",
  DEVELOPER_DIRECTORY_REQUIRED:"所选目录不存在。",
  DEVELOPER_LOOPBACK_HOST_REQUIRED:"此目录未配置为本机开发服务。远程或正式主机请通过连接设置读取。",
  DEVELOPER_CREDENTIAL_REQUIRED:"首次读取此账本需要验证管理员。",
  UNAUTHENTICATED:"管理员验证未通过，请核对所选账本的账号和密码。",
  DEVELOPER_EMPTY_DIRECTORY_REQUIRED:"新建账本需要空目录，已有内容已保留。",
  DEVELOPER_DATA_EXISTS:"当前目录已有账本，请选择新的空目录。",
  BACKUP_DIRECTORY_CONFLICT:"普通备份和隐藏副本请选择不同目录；恢复位置不能覆盖现用数据。",
  DEVELOPER_BUILD_BUSY:"已有封包任务正在运行，请等待完成或取消。",
  DEVELOPER_PACKAGE_CONFIG_INVALID:"请填写有效版本号（如 0.1.0）和安装方式。",
  DEVELOPER_OPERATION_FAILED:"操作未完成，请检查目录、权限和服务状态。",
  OFFLINE_OWNERSHIP_UNCONFIRMED:"来源没有可核对的服务锁记录。请使用此来源导出的 .qbackup 文件读取。",
  OFFLINE_TARGET_INSIDE_SOURCE:"工作副本必须放在来源目录之外。",
  SERVICE_OWNER_BUSY:"此账本已由其他服务占用。",
  WINDOWS_PACKAGING_REQUIRED:"请在 Windows 开发电脑上封包。",
};
function message(e:unknown) { return labels[errorCode(e)] ?? errorMessage(e); }
export function DeveloperPage({app}:{app:Workbench}) {
  const [target,setTarget] = useState<TargetState>({target:null,verified:false});
  const [packageDialog,setPackageDialog] = useState<{delivery:string;permissions:string[]}|null>(null);
  const [state,setState] = useState<Configuration|null>(null);
  const [hidden,setHidden]=useState(""); const [hour,setHour]=useState("23");
  const [restoreFile,setRestoreFile]=useState(""); const [restoreRoot,setRestoreRoot]=useState("");
  const [root,setRoot] = useState(""); const [backup,setBackup] = useState("");
  const [output,setOutput] = useState(""); const [version,setVersion] = useState("0.1.0");
  const [runtime,setRuntime] = useState("downloadBootstrapper");
  const [error,setError] = useState(""); const [busy,setBusy] = useState(false);
  const [available,setAvailable] = useState(false);
  const [dialog,setDialog] = useState<"create"|"authorize"|"restore"|"directory"|null>(null);
  const [username,setUsername] = useState(""); const [password,setPassword] = useState("");
  const locked=useRef(false); const mounted=useRef(true); const hydrated=useRef(false);
  const action = <T,>(op:Record<string,unknown>)=>request<T>("developer",{request:op});
  const accept = (s:Configuration) => { if(!mounted.current)return;setAvailable(true);setState(s);if(!hydrated.current){setRoot(s.root);setBackup(s.backup_dir);setHidden(s.daily?.hidden_dir??"");setHour(String(s.daily?.daily_hour??23));setOutput(s.preferences.output);setVersion(s.preferences.version);setRuntime(s.preferences.runtime);hydrated.current=true;} };
  useEffect(()=>{
    mounted.current=true;
    void action<Configuration>({op:"status"}).then(accept).catch(e=>{if(mounted.current)setError(message(e));});
    const timer=window.setInterval(()=>{if(!locked.current)void action<Configuration>({op:"status"}).then(accept).catch(()=>{if(mounted.current)setAvailable(false);});},1500);
    return()=>{mounted.current=false;window.clearInterval(timer);};
  },[]);
  async function run(work:()=>Promise<void>) {
    if(locked.current||app.busy)return;locked.current=true;setBusy(true);setError("");
    try{await work();}catch(e){if(mounted.current)setError(message(e));}
    finally{locked.current=false;if(mounted.current)setBusy(false);}
  }
  const building=state?.job?.state==="running"||state?.job?.state==="cancelling";
  const disabled=busy||app.busy;
  const connectedToLocal=!!state&&app.connection?.certificate_sha256===state.connection.certificate_sha256;
  async function pick(target:string, update:(v:string)=>void){await run(async()=>{const r=await request<{directory:string|null}>("pick_directory",{target});if(r.directory)update(r.directory);});}
  async function select(initialize:boolean){await run(async()=>{
    // Ask for credentials only for an unknown existing data source, before changing it.
    const op={op:"select",root,initialize,backup_dir:backup,username:username||null,password:password||null};
    try {
      // This workbench entry shares the busy gate with financial actions.
      // Native IPC also blocks switching while a financial receipt is unknown.
      const result=await app.developerOperation(op);
      if(result)setDialog(null);
    } catch(e) {
      if(errorCode(e)==="DEVELOPER_CREDENTIAL_REQUIRED")setDialog("authorize");
      else {if(!initialize&&["UNAUTHENTICATED","ADMIN_REQUIRED"].includes(errorCode(e)))setDialog("authorize");throw e;}
    } finally {setPassword("");}
  });}
  async function pack(delivery:string, permissions:string[]){await run(async()=>{
    accept(await action<Configuration>({op:"save_package",output,version,runtime}));
    accept(await action<Configuration>({op:"package",delivery,permissions}));
  });}
  const job=state?.job;
  const jobLabel=job?({running:"构建中",cancelling:"正在取消",cancelled:"已取消",failed:"封包失败",succeeded:"已完成"})[job.state]:"尚未开始";
  return <section className="developer-page" aria-label="开发部署">
    <div className="developer-title"><h1>开发部署</h1><Badge muted>开发版</Badge></div>
    <div className="developer-grid">
      <section className="card developer-card">
        <div className="developer-heading"><h2>当前读取的数据</h2><small className={available?"developer-connected":"muted"}>{available?"本机服务":"连接不可用"}</small></div>
        <div className="developer-source"><p className="developer-job-path">在线连接：{app.connection?.url??"—"}</p><small>账本：{app.session?.ledger_id??"身份待核对"}</small><Button variant="outline" disabled={disabled||building||app.pending} onClick={()=>void app.editConnection()}>导入或更换 Host 连接</Button></div>
        <h3>本机开发工作副本</h3>
        <div className="developer-path"><Field label="存储位置" compact><Input value={root} onChange={e=>setRoot(e.target.value)} title={root} disabled={disabled||building}/></Field><Button variant="outline" disabled={disabled||building} onClick={()=>void pick("developer_root",setRoot)}>选择目录</Button></div>
        <div className="developer-actions"><Button disabled={disabled||building||app.pending||!root} onClick={()=>{if(root===state?.root)void select(false);else setDialog("directory");}}>读取此位置</Button><Button variant="outline" disabled={disabled||building||app.pending} onClick={()=>setDialog("create")}>新建空账本</Button><Button variant="outline" disabled={disabled||building||app.pending} onClick={()=>{setError("");setDialog("restore");}}>导入备份</Button></div>
        <div className="developer-source"><p>当前账本：{state?.root??"—"}</p><small>{state?.source?`原始来源：${state.source.original} · 工作副本：${state.source.working_copy}`:""}</small><small>{state?`账本标识 ${state.ledger_id}`:"正在读取当前数据源"}</small>{state&&!connectedToLocal&&<small>当前业务连接未读取此账本，点击“读取此位置”连接。</small>}{error&&dialog===null&&<p className="inline-error" role="alert">{error}</p>}</div>
        <div className="developer-path"><Field label="备份位置" compact><Input value={backup} onChange={e=>setBackup(e.target.value)} title={backup} disabled={disabled||building}/></Field><Button variant="outline" disabled={disabled||building} onClick={()=>void pick("developer_backup",setBackup)}>选择目录</Button></div>
        <div className="developer-path"><Field label="隐藏位置" compact><Input value={hidden} onChange={e=>setHidden(e.target.value)} title={hidden} disabled={disabled||building}/></Field><Button variant="outline" disabled={disabled||building} onClick={()=>void pick("developer_hidden",setHidden)}>选择目录</Button></div>
        <Field label="每日时间" compact><Input type="number" min="0" max="23" value={hour} onChange={e=>setHour(e.target.value)} disabled={disabled||building} aria-label="每日备份小时（北京时间）"/></Field>
        <div className="developer-actions"><Button variant="outline" disabled={disabled||building||app.pending||!backup||!hidden||hour===""} onClick={()=>void run(async()=>{const r=await app.developerOperation({op:"daily_backup",directory:backup,hidden,hour:Number(hour)});if(r)accept(r as unknown as Configuration);})}>保存备份设置</Button><Button variant="ghost" disabled={disabled||building||app.pending||!connectedToLocal} onClick={()=>void run(async()=>{await app.makeBackup(true);accept(await action<Configuration>({op:"status"}));})}>生成今日备份</Button></div>
        <small className="muted">北京时间整点执行；每天一份恢复数据 + Excel。隐藏位置仅开发者可设置。</small>
        {state?.daily_result?.hidden?.ok===false&&<small className="inline-error">隐藏副本未完成，请核对隐藏位置后重试今日备份。</small>}
        <small className="muted">最近备份 {state?.last_backup?.created_at?stamp(state.last_backup.created_at):"尚无备份"}</small>
      </section>
      <PackageChoices disabled={!!(disabled||building)} ready={available} target={target} onTarget={setTarget}
        output={output} version={version} runtime={runtime} onOutput={()=>void pick("developer_output",setOutput)}
        onVersion={setVersion} onRuntime={setRuntime} onPackage={(delivery,permissions)=>setPackageDialog({delivery,permissions})}/>

    </div>
    <section className="card developer-card" aria-live="polite">
      <div className="developer-heading"><h2>封包任务</h2><div className="developer-actions"><small className="muted">{jobLabel}</small>{building&&<Button variant="outline" disabled={disabled||job?.state==="cancelling"} onClick={()=>void run(async()=>accept(await action<Configuration>({op:"cancel"})))}>取消封包</Button>}{job?.state==="succeeded"&&<Button variant="outline" disabled={disabled} onClick={()=>void run(async()=>accept(await action<Configuration>({op:"open_output"})))}>打开产物目录</Button>}</div></div>
      {job?<><p className="developer-job-path">{job.delivery==="manager"?"母版":"子版"} · {job.version}　{job.output}</p>{job.bytes!==null&&<small className="muted">产物合计 {(job.bytes/1024/1024).toFixed(1)} MB　源码 {job.source_commit?.slice(0,7)}</small>}{job.error&&<p className="inline-error">构建未完成，请查看下方日志。</p>}{job.lines.length>0&&<details open={job.state==="failed"}><summary>查看构建日志</summary><pre className="developer-log">{job.lines.join("\n")}</pre></details>}</>:<p className="muted">选择母版或子版后，这里显示构建进度与产物位置。</p>}
    </section>
    <Modal open={packageDialog!==null} onOpenChange={v=>!v&&setPackageDialog(null)} title="确认正式封包" compact><p>{packageDialog?.delivery==="sales"?"子版":"母版"} · {version}</p><p className="developer-job-path">目标：{target.target?.connection.url}<br/>账本：{target.target?.ledger_id}<br/>产物：{output}</p><p>已选择：{permissionCatalog.filter(p=>packageDialog?.permissions.includes(p.id)).map(p=>p.label).join("、")}。登录、退出与内部连接提示始终隐藏。</p><p>当前使用单个 Host；尚不支持自动切换或故障接管。</p><div className="dialog-actions"><Button variant="outline" disabled={disabled} onClick={()=>setPackageDialog(null)}>取消</Button><Button disabled={disabled} onClick={()=>{const selection=packageDialog;setPackageDialog(null);if(selection)void pack(selection.delivery,selection.permissions);}}>开始封包</Button></div></Modal>
    <Modal open={dialog!==null} onOpenChange={v=>{if(!disabled){setDialog(v?dialog:null);setPassword("");}}} title={dialog==="directory"?"读取离线业务目录":dialog==="restore"?"导入备份":dialog==="create"?"新建空账本":"验证管理员"} compact className={`developer-dialog${dialog==="restore"?" developer-restore-dialog":""}`}>
      {error&&<p className="inline-error" role="alert">{error}</p>}
      {dialog==="directory"?<><p className="developer-job-path">原始来源：{root}</p><p>仅支持已停止服务的兼容业务目录。验证管理员后创建独立工作副本，修改只保存在副本。</p><div className="developer-path"><Field label="工作副本位置" compact><Input disabled={disabled} value={restoreRoot} onChange={e=>setRestoreRoot(e.target.value)}/></Field><Button variant="outline" disabled={disabled} onClick={()=>void pick("developer_restore",setRestoreRoot)}>选择目录</Button></div><Field label="来源管理员账号" compact><Input disabled={disabled} value={username} onChange={e=>setUsername(e.target.value)}/></Field><Field label="来源管理员密码" compact><Input disabled={disabled} type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></Field></>:dialog==="restore"?<><p>恢复到新的空目录，当前账本与草稿保留。</p><div className="developer-path"><Field label="恢复文件" compact><Input disabled={disabled} value={restoreFile} onChange={e=>setRestoreFile(e.target.value)}/></Field><Button variant="outline" disabled={disabled} onClick={()=>void pick("developer_recovery_file",setRestoreFile)}>选择文件</Button></div><div className="developer-path"><Field label="新存储位置" compact><Input disabled={disabled} value={restoreRoot} onChange={e=>setRestoreRoot(e.target.value)}/></Field><Button variant="outline" disabled={disabled} onClick={()=>void pick("developer_restore",setRestoreRoot)}>选择目录</Button></div></>:dialog==="create"?<><p className="developer-job-path">账本：{root}<br/>备份：{backup}</p><p>在空数据目录中初始化新账本。备份目录的已有文件、当前账本与草稿保留。</p></>:<><p>使用所选账本已有的管理员身份读取。</p><Field label="管理员账号" compact><Input autoComplete="username" value={username} onChange={e=>setUsername(e.target.value)}/></Field><Field label="密码" compact><Input type="password" autoComplete="current-password" value={password} onChange={e=>setPassword(e.target.value)}/></Field></>}
      <div className="dialog-actions"><Button variant="outline" disabled={disabled} onClick={()=>setDialog(null)}>取消</Button><Button disabled={disabled||(dialog==="restore"&&(!restoreFile||!restoreRoot))} onClick={()=>void (dialog==="directory"?run(async()=>{try{await app.developerOperation({op:"import_directory",root,target:restoreRoot,username,password});setDialog(null);}finally{setPassword("");}}):dialog==="restore"?run(async()=>{const r=await app.developerOperation({op:"restore_data",package:restoreFile,target:restoreRoot});if(r){hydrated.current=false;accept(r as unknown as Configuration);setDialog(null);}}):select(dialog==="create"))}>{dialog==="directory"?"验证并读取副本":dialog==="restore"?"导入并读取":dialog==="create"?"创建并读取":"验证并读取"}</Button></div>
    </Modal>
  </section>;
}
