import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { allowed, type Permission } from "./permissions";
import { setDeliveryContext, formalPresentation, showError } from "./formalPresentation";
import { errorCode, errorMessage, request } from "../bridge";
import type {
  CustomerGroup,
  CustomerListing,
  Calculation,
  Catalog,
  Connection,
  Job,
  JobListing,
  Listing,
  Order,
  Preferences,
  ProfitAnalysis,
  AnalysisFilters,
  Session,
} from "../contracts";
import { backupReceipt } from "../features/settings/backupPresentation";
import { selectDraftSource } from "./developerDraft";
import { profitRange, type ProfitPreset } from "./profit";
import { draftReducer, restorableDraft, snapshot, draftContext } from "./draft";
import { uiDiagnostic } from "./uiDiagnostics";
import { persistDraft, savedDraft, savedContext, type SavedInput } from "./localSave";
export type Route =
  | "quote"
  | "orders"
  | "detail"
  | "prices"
  | "profit"
  | "tasks"
  | "developer"
  | "settings";
type Refreshed<T> = { value: T | null; error?: unknown };
async function afterSaved<T>(read: () => Promise<T>): Promise<Refreshed<T>> {
  try {
    return { value: await read() };
  } catch (error) {
    return { value: null, error };
  }
}
export function useWorkbench() {
  const [delivery, setDelivery] = useState("loading");
  const [permissions,setPermissions] = useState<string[]|null>(null);
  const [connected,setConnected] = useState(false);
  const formal = ["manager","sales"].includes(delivery) || formalPresentation();
  const can = (id:Permission) => allowed(permissions,session?.role,id);
  const [connectionDialog,setConnectionDialog] = useState(false);
  const [developerTools, setDeveloperTools] = useState(false);
  const [automatic, setAutomatic] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [draft, dispatch] = useReducer(draftReducer, null, () =>
    restorableDraft(localStorage.getItem("777-desktop-draft-v1")),
  );
  const [draftChange, setDraftChange] = useState<(() => void) | null>(null);
  const [route, setRoute] = useState<Route>("quote");
  const [feedback, setFeedback] = useState("");
  const [saveFailure, setSaveFailure] = useState("");
  const [matchRequest, setMatchRequest] = useState(0);

  const [isError, setIsError] = useState(false);
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState(false);
  const [listing, setListing] = useState<Listing | null>(null);
  const [filters, setFilters] = useState({
    q: "",
    state: "",
    offset: 0,
    view: "",
  });
  const [analysis, setAnalysis] = useState<ProfitAnalysis | null>(null);
  const [analysisPreset, setAnalysisPreset] = useState<ProfitPreset | null>(
    "day",
  );
  const [analysisFilters, setAnalysisFilters] = useState<AnalysisFilters>(() =>
    profitRange("day"),
  );
  const [selected, setSelected] = useState<Order | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [jobsMore,setJobsMore]=useState<boolean|undefined>(undefined);
  const [jobsOffset,setJobsOffset]=useState(0),[jobsTotal,setJobsTotal]=useState(0);
  function acceptJobs(v:JobListing|null) {setJobsMore(v?.has_more);setJobs(v?.jobs??[]);setJobsOffset(v?.offset??0);setJobsTotal(v?.total??v?.jobs.length??0);}
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [backup, setBackup] = useState<Record<string, unknown> | null>(null);
  const listScrollRef = useRef(0);
  const epoch = useRef(0);
  const busyRef = useRef(false);
  const draftSource = useRef<string | null>((() => {
    try { return JSON.parse(localStorage.getItem("777-desktop-draft-v1") ?? "null")?.source_pin ?? null; }
    catch { return null; }
  })());
  function bindDeveloperDraft(pin: string) {
    const next = selectDraftSource(localStorage, draftSource.current, pin);
    draftSource.current = pin;
    dispatch({type:"restore", raw:next});
  }
  useEffect(() => {
    try {
      persistDraft(draft,draftSource.current);
    } catch {
      uiDiagnostic("frontend_error", undefined, new Error("draft storage unavailable"));
      setFeedback(formalPresentation() ? "" : "当前草稿无法保存到本机，请保持窗口打开。");
      setIsError(true);
    }
  }, [draft.details, draft.lines, draft.editing, draft.customer,draft.saveId]);
  useEffect(() => { uiDiagnostic("draft_context", draft); }, [draft.editing?.order_id, draft.editing?.revision]);
  const run = useCallback(
    async <T>(work: () => Promise<T>, done?: (v: T) => void, rethrow = false) => {
      if (busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setFeedback("");
      setIsError(false);
      const current = epoch.current;
      try {
        const result = await work();
        if (current === epoch.current) done?.(result);
        return result;
      } catch (e) {
        if (e instanceof Error) uiDiagnostic("frontend_error", undefined, e);
        if (rethrow) throw e;
        if (current === epoch.current) {
          setFeedback(errorMessage(e));
          setIsError(true);
          const code = errorCode(e);
          if (formalPresentation() && !showError(code)) setConnected(false);
          if (
            ["COMMIT_UNKNOWN", "PENDING_REQUEST_REQUIRES_QUERY"].includes(code)
          )
            setPending(true);
          if (
            [
              "UNAUTHENTICATED",
              "DEVICE_NOT_AUTHORIZED",
              "AUTOMATIC_AUTHORIZATION_DENIED",
              "AUTOMATIC_IDENTITY_CONFLICT",
              "DELIVERY_ROLE_MISMATCH",
            ].includes(code)
          ) {
            epoch.current++;
            setSession(null);
            setSelected(null);
          setDraftChange(null);
            setCatalog(null);
            setListing(null);
            setAnalysis(null);
            acceptJobs(null);
            setBackup(null);
            setPreferences(null);
            dispatch({ type: "invalidate" });
          }
          if (
            [
              "PRICE_VERSION_CHANGED",
              "PRICE_STALE",
              "CALCULATION_STALE",
              "CALCULATION_REQUIRED",
            ].includes(code)
          )
            dispatch({ type: "invalidate" });
        }
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [],
  );
  useEffect(() => {
    request<{
      delivery: string;
      developer_tools?: boolean;
      automatic: boolean;
      connection: Connection | null;
      pending: boolean;
      permissions: string[]|null;
    }>("connection")
      .then((r) => {
        setDeliveryContext(r.delivery);
        setPermissions(r.permissions ?? null);
        setDelivery(r.delivery);
        setAutomatic(r.automatic);
        const tools = r.delivery === "development" && !!r.developer_tools;
        setDeveloperTools(tools);
        if (tools) setRoute("developer");
        if (r.automatic) void bootstrap();
        setConnection(r.connection);
        setPending(r.pending);
      })
      .catch((e) => {
        setDelivery("unavailable");
        setAutomatic(true);
        setFeedback(errorMessage(e));
        setIsError(true);
      });
  }, []);
  function savedFeedback<T>(r: Refreshed<T>, message: string) {
    setFeedback(r.error && message && !formalPresentation() ? `${message}但视图刷新失败，请重新读取。` : message);
    setIsError(!!r.error);
    if (r.error && errorCode(r.error) === "UNAUTHENTICATED") {
      epoch.current++;
      setSession(null);
      setSelected(null);
      setCatalog(null);
      setListing(null);
      setAnalysis(null);
      acceptJobs(null);
      setBackup(null);
      setPreferences(null);
      dispatch({ type: "invalidate" });
      setFeedback(formalPresentation() ? message : `${message}连接已失效，请重新连接后读取。`);
      setConnected(false);
    }
  }
  async function bootstrap() {
    await run(
      async () => {
        const b = await request<{
          delivery: string;
          automatic: boolean;
          session: Session | null;
        }>("bootstrap");
        const p = b.session ? await request<Catalog>("prices").catch(e => { if (errorCode(e) === "PRICES_NOT_PUBLISHED") return null; throw e; }) : null;
        const policy = await request<{permissions:string[]|null;developer_tools?:boolean}>("connection");
        const dirs = b.session && allowed(policy.permissions ?? null,b.session.role,"settings") ? await request<Preferences>("settings").catch(e=>{if(["manager","sales"].includes(b.delivery))return null;throw e;}) : null;
        const c = b.session
          ? await request<{ connection: Connection | null }>("connection")
          : null;
        // An editing draft from a broader package must not re-enable that UI.
        // Preserve it separately before showing a new permitted draft.
        const restrictedDraft = !!b.session && !!draft.editing && !allowed(policy.permissions ?? null,b.session?.role,"edit_orders");
        if (restrictedDraft) {
          const raw=localStorage.getItem("777-desktop-draft-v1");
          if(raw) localStorage.setItem(`777-desktop-restricted-draft-${draft.editing!.order_id}`,raw);
        }
        const localSaved = b.session && ["manager","sales"].includes(b.delivery) ? await savedDraft(draft.saveId) : null;
        return { b, p, dirs, c, policy, restrictedDraft, localSaved };
      },
      ({ b, p, dirs, c, policy, restrictedDraft, localSaved }) => {
        setDeliveryContext(b.delivery);
        setPermissions(policy.permissions ?? null);
        setDeveloperTools(b.delivery === "development" && !!policy.developer_tools);
        setConnected(!!b.session);
        if (b.delivery === "development" && c?.connection) bindDeveloperDraft(c.connection.certificate_sha256);
        if (c) setConnection(c.connection);
        epoch.current++;
        setDelivery(b.delivery);
        setAutomatic(b.automatic);
        setSession(b.session);
        if (restrictedDraft) dispatch({type:"reset"});
        else if (localSaved?.result && localSaved.submitted) dispatch({type:"committed",snapshot:localSaved.submitted.snapshot,details:localSaved.submitted.details,context:savedContext(localSaved.submitted)});
        dispatch({ type: "invalidate" });
        setCatalog(p);
        setPreferences(dirs);
        setPending(b.session?.pending ?? false);
        if (p) dispatch({ type: "prices", version: p.price_version_id });
        setRoute(!b.session && policy.developer_tools ? "developer" : "quote");
      },
    );
  }
  async function connect(c: Connection) {
    await run(
      async () => {
        const s = await request<Session & {catalog:Catalog|null;settings:Preferences}>("connect", {
          connection: c,
        });
        const p=s.catalog, dirs=s.settings;
        return { s, p, dirs };
      },
      ({ s, p, dirs }) => {
        setConnected(true);
        if(delivery === "development") bindDeveloperDraft(c.certificate_sha256);
        epoch.current++;
        setConnectionDialog(false);
        setConnection(c);
        setSession(s);
        setSelected(null);
        setListing(null);
        setAnalysis(null);
        acceptJobs(null);
        setBackup(null);
        setPending(s.pending);
        setCatalog(p);
        setPreferences(dirs);
        if(p) dispatch({ type: "prices", version: p.price_version_id });
        setRoute("quote");
      },
      true,
    );
  }
  const loadOrders = useCallback(
    (next = filters) =>
      run(
        async () => {
          try { return await request<Listing>("orders",next); }
          catch(e) { if(errorCode(e)!=="QUERY_VIEW_CHANGED")throw e;return request<Listing>("orders",{...next,offset:0,view:""}); }
        },
        (v) => {
          setListing(v);
          setFilters({ ...next,offset:v.offset, view: v.view });
        },
      ),
    [filters, run],
  );
  const loadAnalysis = (
    next?: AnalysisFilters,
    preset: ProfitPreset | null = analysisPreset,
  ) => {
    const resolved =
      next ??
      (preset
        ? { ...profitRange(preset), period: analysisFilters.period }
        : analysisFilters);
    return run(
      () => request<ProfitAnalysis>("analytics", { ...resolved }),
      (value) => {
        setAnalysis(value);
        setAnalysisFilters(resolved);
        setAnalysisPreset(preset);
      },
    );
  };
  const pickDirectory = (target: "export_dir" | "image_dir") =>
    run(() =>
      request<{ directory: string | null }>("pick_directory", { target }),
    );
  const readOrder = useCallback(
    (id: string) =>
      run(
        () => request<Order>("order", { order_id: id }),
        (v) => {
          setSelected(v);
          setRoute("detail");
        },
      ),
    [run],
  );
  function guardDraft(work: () => void) {
    if (pending || busy) return;
    if (draft.lines.length) {
      uiDiagnostic("draft_switch_requested", draft);
      setDraftChange(() => work);
    } else work();
  }
  const beginEdit = (order_id:string) => run(() => {
    uiDiagnostic("edit_requested", draft);
    return request<Order>("order",{order_id});
  },order => {
    if(order.state!=="active")return;
    setMatchRequest(0);setSaveFailure("");
    // Reading details/history does not abandon the draft. Resume this same
    // saved version without replacing any in-progress line changes.
    if (draft.editing?.order_id === order.order_id && draft.editing.revision === order.revision) {
      uiDiagnostic("edit_resumed", draft);
      setDraftChange(null);
      setSelected(order);
      setRoute("quote");
      return;
    }
    const work=()=>{uiDiagnostic("edit_loaded", draft);dispatch({type:"load_order",order});setSelected(order);setRoute("quote");};
    if(draft.lines.length){uiDiagnostic("draft_switch_requested", draft);setDraftChange(()=>work);}else work();
  });
  function chooseCustomer(group:CustomerGroup, reset=false) {
    const first=group.orders[0];if(!first)return;
    const details={...group.details,order_ref:reset?"":draft.details.order_ref};
    const customer=first.customer_id?{customer_id:first.customer_id}:{anchor_order_id:first.order_id};
    const work=()=>{dispatch({type:reset?"customer":"link_customer",details,customer});setSaveFailure("");setMatchRequest(0);setFeedback("");setIsError(false);setRoute("quote");};
    if(reset)guardDraft(work);else work();
  }
  const customerOrders = (query:string,offset=0,group_id?:string,order_offset=0) => request<CustomerListing>("customer_orders",{query,offset,group_id:group_id??null,order_offset});
  const refreshPrices = () =>
    run(
      () => request<Catalog>("prices"),
      (p) => {
        setCatalog(p);
        if(p) dispatch({ type: "prices", version: p.price_version_id });
      },
    );
  const calculate = () => {
    const stalePrice=["PRICE_VERSION_CHANGED","PRICE_STALE"].includes(saveFailure);
    const revision = stalePrice ? (BigInt(draft.revision)+1n).toString() : draft.revision;
    return run(
      async () => {
        const prices=stalePrice ? await request<Catalog>("prices") : null;
        const v=await request<{draft_revision:string;result:Calculation}>("order_preview", {
          snapshot:{...snapshot(draft),price_version_id:prices?.price_version_id ?? draft.priceVersion},
          sources:draft.lines.map(l=>l.source??null),
          order_id:draft.editing?.order_id??null,
          expected_revision:draft.editing?.revision??null,
          draft_revision:revision,
        });
        return {...v,prices};
      },
      (v) => {
        if(v.prices){setCatalog(v.prices);dispatch({type:"prices",version:v.prices.price_version_id});}
        dispatch({type:"calculated",revision:v.draft_revision,result:v.result});
        setSaveFailure("");
      },
    );
  };
  const submit = () => {
    const context=draftContext(draft);
    const submitted = snapshot(draft),
      details = draft.details;
    return run(
      async () => {
        setSaveFailure("");
        uiDiagnostic("save_requested", draft);
        persistDraft(draft,draftSource.current);
        let committed:SavedInput={snapshot:submitted,details,...context};
        let receipt:{order_id:string};
        try {
          receipt=await request<{order_id:string}>("save_order",{...committed,draft_revision:draft.revision,operation_id:draft.saveId});
        } catch(e) {
          const saved=await savedDraft(draft.saveId);
          if(!saved?.result||!saved.submitted) {
            const code=errorCode(e);
            setSaveFailure(code);
            if (["CUSTOMER_SELECTION_REQUIRED", "CUSTOMER_IDENTITY_CONFLICT", "CUSTOMER_ORDER_NUMBER_EXISTS"].includes(code)) setMatchRequest(v=>v+1);
            throw e;
          }
          receipt=saved.result;committed=saved.submitted;
        }
        const value=can("orders") ? await afterSaved(()=>request<Order>("order",{order_id:receipt.order_id})) : {value:null};
        return {...value,committed};
      },
      (r) => {
        setPending(false);
        uiDiagnostic("save_confirmed", draft);
        dispatch({ type: "committed", snapshot:r.committed.snapshot, details:r.committed.details,context:savedContext(r.committed) });
        setSelected(r.value);
        setListing(null);
        setAnalysis(null);
        setRoute(can("orders") ? (r.value ? "detail" : "orders") : "quote");
        savedFeedback(r, "订单已保存。");
      },
    );
  };
  const note = (body: string) => {
    if (!selected) return Promise.resolve();
    const id = selected.order_id;
    return run(
      async () => {
        await request("note", {
          order_id: id,
          expected_revision: selected.revision,
          body,
        });
        return afterSaved(() => request<Order>("order", { order_id: id }));
      },
      (r) => {
        setSelected(r.value);
        setListing(null);
        setAnalysis(null);
        if (!r.value) setRoute("orders");
        savedFeedback(r, "备注已追加，原记录保留。");
      },
    );
  };
  const changeState = (reason: string) => {
    if (!selected) return Promise.resolve();
    const id = selected.order_id;
    return run(
      async () => {
        await request("set_state", {
          order_id: id,
          expected_revision: selected.revision,
          state: selected.state === "active" ? "void" : "active",
          reason,
        });
        return afterSaved(() => request<Order>("order", { order_id: id }));
      },
      (r) => {
        setSelected(r.value);
        setListing(null);
        setAnalysis(null);
        if (!r.value) setRoute("orders");
        savedFeedback(
          r,
          selected.state === "active"
            ? "订单已作废，原金额与备注保留。"
            : "订单已恢复。",
        );
      },
    );
  };
  const publish = (items: Catalog["items"]) =>
    run(
      async () => {
        await request("publish_prices", {
          prices: { price_version_id: crypto.randomUUID(), items },
          expected_price_version_id: catalog?.price_version_id ?? null,
        });
        return afterSaved(() => request<Catalog>("prices"));
      },
      (r) => {
        if (r.value) {
          setCatalog(r.value);
          dispatch({ type: "prices", version: r.value.price_version_id });
        } else {
          setCatalog(null);
          dispatch({ type: "invalidate" });
        }
        savedFeedback(
          r,
          "新价格已发布，已有订单保持原价格。请重新计算并核对草稿。",
        );
      },
    );
  const loadJobs = useCallback(
    (offset=jobsOffset) => run(()=>request<JobListing>("outputs",{offset}),acceptJobs),
    [run,jobsOffset],
  );
  const output = (kind: string) =>
    selected &&
    run(
      async () => {
        await request("create_output", {
          order_id: selected.order_id,
          expected_revision: selected.revision,
          kind,
        });
        return afterSaved(() => request<JobListing>("outputs"));
      },
      (r) => {
        acceptJobs(r.value);
        setRoute("tasks");
        savedFeedback(r, "输出任务已创建，订单不会重复入账。");
      },
    );
  const retryOutput = (id: string) =>
    run(
      async () => {
        await request("retry_output", { job_id: id });
        return afterSaved(() => request<JobListing>("outputs",{offset:jobsOffset}));
      },
      (r) => {
        acceptJobs(r.value);
        savedFeedback(r, "原输出任务已重试。");
      },
    );
  const recover = (retry: boolean) =>
    run(
      () =>
        request<{
          pending: boolean;
          result: { order_id?: string } | null;
          path?: string;
          submitted?: { snapshot: unknown; details: unknown; order_id?:string; expected_revision?:string; sources?:unknown; customer?:unknown };
        }>("recover", { retry }),
      (v) => {
        setPending(v.pending);
        if (!v.pending && v.result) {
          setFeedback("原请求已确认保存。");
          if (v.path === "/v1/orders" || v.path === "/v1/order-save") {
            if (v.submitted)
              dispatch({
                type: "committed",
                snapshot: v.submitted.snapshot,
                details: v.submitted.details,
                context:v.path==="/v1/order-save"?{order_id:v.submitted.order_id??null,expected_revision:v.submitted.expected_revision==null?null:String(v.submitted.expected_revision),sources:v.submitted.sources,customer:v.submitted.customer??{}}:undefined,
              });
            else dispatch({ type: "invalidate" });
          }
          setListing(null);
          setAnalysis(null);
        } else
          setFeedback(formalPresentation() ? "" :
            v.pending
              ? "服务尚无原请求回执，可按原请求重试。"
              : "没有待核查请求。",
          );
      },
    );
  const loadSettings = () =>
    run(
      async () => ({
        p: await request<Preferences>("settings"),
        b:
          can("backup")
            ? await request<Record<string, unknown>>("backup_status")
            : null,
      }),
      (v) => {
        setPreferences(v.p);
        setBackup(v.b);
      },
    );
  const saveSettings = (export_dir: string, image_dir: string) =>
    preferences &&
    run(
      () =>
        request<Preferences>("save_settings", {
          revision: preferences.revision,
          export_dir,
          image_dir,
        }),
      (v) => {
        setPreferences(v);
        setFeedback("位置已发布，销售端自动继承。");
      },
    );
  const makeBackup = (rethrow = false) =>
    run(
      async () => {
        const receipt = await request<Record<string, unknown>>("backup");
        const refreshed = await afterSaved(() => request<Record<string, unknown>>("backup_status"));
        return {receipt, refreshed};
      },
      ({receipt,refreshed}) => {
        setBackup(refreshed.value ?? {...backup,last_success:receipt,delivery_complete:receipt.delivery_complete});
        savedFeedback(refreshed, backupReceipt(receipt));
      },
      rethrow,
    );
  const logout = () =>
    run(
      async () => {
        try {
          await request("disconnect");
        } finally {
          epoch.current++;
          setSession(null);
          setCatalog(null);
          setSelected(null);
          setListing(null);
          setAnalysis(null);
          acceptJobs(null);
          setBackup(null);
          setPreferences(null);
          dispatch({ type: "invalidate" });
        }
      },
      () => {},
    );
  async function editConnection() {
    guardDraft(()=>setConnectionDialog(true));
  }
  function navigate(next: Route) {
    const required:Partial<Record<Route,Permission>>={orders:"orders",detail:"orders",prices:"prices",profit:"finance",tasks:"exports",settings:"settings"};
    if(required[next] && !can(required[next]!)) return;
    setRoute(next);
    if (next === "profit") void loadAnalysis();
    if (next === "orders") void loadOrders({ ...filters, view: "" });
    if (next === "tasks") void loadJobs();
    if (next === "settings") void loadSettings();
  }
  const retry = useRef<() => void>(()=>{});
  retry.current = () => {
    if (busyRef.current) return;
    if (!connected || !session) void bootstrap();
    else if (pending) void recover(true);
  };
  useEffect(() => {
    if (!formal) return;
    const timer = window.setInterval(()=>retry.current(), 2000);
    return ()=>window.clearInterval(timer);
  },[formal]);
  return {
    formal, can, permissions, developerTools,
    async developerOperation(operation: Record<string, unknown>) {
      return run(async () => {
        const result = await request<{connection:{certificate_sha256:string}}>("developer", {request:operation});
        if (["select","restore_data","import_directory"].includes(String(operation.op))) {
          bindDeveloperDraft(result.connection.certificate_sha256);
          window.location.reload();
        }
        return result;
      }, undefined, true);
    },
    draftChange,
    confirmDraftChange:()=>{const work=draftChange;uiDiagnostic("draft_switch_confirmed",draft);setDraftChange(null);work?.();},
    resumeDraft:()=>{uiDiagnostic("draft_continued",draft);setDraftChange(null);setRoute("quote");},
    cancelDraftChange:()=>setDraftChange(null),
    cancelEdit:()=>guardDraft(()=>{dispatch({type:"reset"});setRoute("orders");void loadOrders({...filters,view:""});}),
    beginEdit,
    chooseCustomer,
    chooseNewCustomer:()=>{dispatch({type:"link_customer",details:draft.details,customer:{new_customer:true}});setSaveFailure("");setMatchRequest(0);setFeedback("");setIsError(false);},
    customerOrders,
    listScrollRef,
    delivery,
    automatic,
    bootstrap,
    editConnection,
    connectionDialog,
    closeConnectionDialog:()=>setConnectionDialog(false),
    session,
    connection,
    catalog,
    draft,
    dispatch,
    route,
    navigate,
    feedback,
    saveFailure, matchRequest,
    isError,
    busy: busy || (formal && !connected),
    pending,
    analysis,
    analysisFilters,
    analysisPreset,
    loadAnalysis,
    pickDirectory,
    listing,
    filters,
    selected,
    jobs,
    preferences,
    backup,
    connect,
    calculate,
    submit,
    note,
    changeState,
    refreshPrices,
    loadOrders,
    readOrder,
    publish,
    loadJobs,
    jobsOffset,jobsTotal,jobsMore,
    output,
    retryOutput,
    createReport:(from:string,to:string)=>run(async()=>{await request("create_report",{from,to});return afterSaved(()=>request<JobListing>("outputs"));},r=>{acceptJobs(r.value);savedFeedback(r,"内部财务报表任务已创建。");}),
    openOutputFolder: (job_id: string) => run(() => request("open_output_folder", {job_id})),
    recover,
    loadSettings,
    saveSettings,
    makeBackup,
    logout,
  };
}
export type Workbench = ReturnType<typeof useWorkbench>;
