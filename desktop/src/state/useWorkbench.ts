import { useCallback, useEffect, useReducer, useRef, useState } from "react";
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
import { selectDraftSource } from "./developerDraft";
import { profitRange, type ProfitPreset } from "./profit";
import { draftReducer, restorableDraft, snapshot, draftContext } from "./draft";
import { uiDiagnostic } from "./uiDiagnostics";
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
  const [connectionDialog,setConnectionDialog] = useState(false);
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
  const [jobsOffset,setJobsOffset]=useState(0),[jobsTotal,setJobsTotal]=useState(0);
  function acceptJobs(v:JobListing|null) {setJobs(v?.jobs??[]);setJobsOffset(v?.offset??0);setJobsTotal(v?.total??v?.jobs.length??0);}
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
      localStorage.setItem(
        "777-desktop-draft-v1",
        JSON.stringify({
          schema: "777-desktop-draft-v1",
          ...(draftSource.current ? {source_pin:draftSource.current} : {}),
          details: draft.details,
          lines: draft.lines,
          editing: draft.editing,
          customer: draft.customer,
        }),
      );
    } catch {
      setFeedback("当前草稿无法保存到本机，请保持窗口打开。");
      setIsError(true);
    }
  }, [draft.details, draft.lines, draft.editing, draft.customer]);
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
          if (
            ["COMMIT_UNKNOWN", "PENDING_REQUEST_REQUIRES_QUERY"].includes(code)
          )
            setPending(true);
          if (
            [
              "UNAUTHENTICATED",
              "DEVICE_NOT_AUTHORIZED",
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
      automatic: boolean;
      connection: Connection | null;
      pending: boolean;
    }>("connection")
      .then((r) => {
        setDelivery(r.delivery);
        setAutomatic(r.automatic);
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
    setFeedback(r.error ? `${message}但视图刷新失败，请重新读取。` : message);
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
      setFeedback(`${message}连接已失效，请重新连接后读取。`);
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
        const dirs = b.session ? await request<Preferences>("settings") : null;
        const c = b.session
          ? await request<{ connection: Connection | null }>("connection")
          : null;
        return { b, p, dirs, c };
      },
      ({ b, p, dirs, c }) => {
        if (b.delivery === "development" && c?.connection) bindDeveloperDraft(c.connection.certificate_sha256);
        if (c) setConnection(c.connection);
        epoch.current++;
        setDelivery(b.delivery);
        setAutomatic(b.automatic);
        setSession(b.session);
        setCatalog(p);
        setPreferences(dirs);
        setPending(b.session?.pending ?? false);
        if (p) dispatch({ type: "prices", version: p.price_version_id });
        setRoute("quote");
      },
    );
  }
  async function connect(c: Connection, username: string, password: string) {
    await run(
      async () => {
        const s = await request<Session & {catalog:Catalog|null;settings:Preferences}>("connect", {
          connection: c,
          username,
          password,
        });
        const p=s.catalog, dirs=s.settings;
        return { s, p, dirs };
      },
      ({ s, p, dirs }) => {
        if(delivery === "development") bindDeveloperDraft(c.certificate_sha256);
        epoch.current++;
        setConnectionDialog(false);
        setConnection(c);
        setSession(s);
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
        () => request<Listing>("orders", next),
        (v) => {
          setListing(v);
          setFilters({ ...next, view: v.view });
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
    const work=()=>{dispatch({type:reset?"customer":"link_customer",details,customer});setRoute("quote");};
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
    const revision = draft.revision;
    return run(
      () =>
        request<{ draft_revision: string; result: Calculation }>("order_preview", {
          snapshot: snapshot(draft),
          sources:draft.lines.map(l=>l.source??null),
          order_id:draft.editing?.order_id??null,
          expected_revision:draft.editing?.revision??null,
          draft_revision: revision,
        }),
      (v) => {
        dispatch({
          type: "calculated",
          revision: v.draft_revision,
          result: v.result,
        });
      },
    );
  };
  const submit = () => {
    const context=draftContext(draft);
    const submitted = snapshot(draft),
      details = draft.details;
    return run(
      async () => {
        uiDiagnostic("save_requested", draft);
        const receipt = await request<{ order_id: string }>("save_order", {
          snapshot: submitted,
          sources:draft.lines.map(l=>l.source??null),
          order_id:draft.editing?.order_id??null,
          expected_revision:draft.editing?.revision??null,
          customer:draft.customer??{},
          details,
          draft_revision: draft.revision,
        });
        return afterSaved(() =>
          request<Order>("order", { order_id: receipt.order_id }),
        );
      },
      (r) => {
        setPending(false);
        uiDiagnostic("save_confirmed", draft);
        dispatch({ type: "committed", snapshot: submitted, details,context });
        setSelected(r.value);
        setListing(null);
        setAnalysis(null);
        setRoute(r.value ? "detail" : "orders");
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
          setFeedback(
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
          session?.role === "admin"
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
        await request("backup");
        return afterSaved(() =>
          request<Record<string, unknown>>("backup_status"),
        );
      },
      (r) => {
        setBackup(r.value);
        savedFeedback(r, "维护备份已完成并核对。");
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
    setRoute(next);
    if (next === "profit") void loadAnalysis();
    if (next === "orders") void loadOrders({ ...filters, view: "" });
    if (next === "tasks") void loadJobs();
    if (next === "settings") void loadSettings();
  }
  return {
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
    isError,
    busy,
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
    jobsOffset,jobsTotal,
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
