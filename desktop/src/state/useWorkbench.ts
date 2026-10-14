import { useCallback, useEffect, useReducer, useRef, useState } from "react";
import { errorCode, errorMessage, request } from "../bridge";
import type {
  Calculation,
  Catalog,
  Connection,
  Job,
  Listing,
  Order,
  Preferences,
  Session,
} from "../contracts";
import { draftReducer, restorableDraft, snapshot } from "./draft";
export type Route =
  | "quote"
  | "orders"
  | "detail"
  | "prices"
  | "profit"
  | "tasks"
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
  const [session, setSession] = useState<Session | null>(null);
  const [connection, setConnection] = useState<Connection | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [draft, dispatch] = useReducer(draftReducer, null, () =>
    restorableDraft(localStorage.getItem("777-desktop-draft-v1")),
  );
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
  const [selected, setSelected] = useState<Order | null>(null);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [preferences, setPreferences] = useState<Preferences | null>(null);
  const [backup, setBackup] = useState<Record<string, unknown> | null>(null);
  const listScrollRef = useRef(0);
  const epoch = useRef(0);
  const busyRef = useRef(false);
  useEffect(() => {
    try {
      localStorage.setItem(
        "777-desktop-draft-v1",
        JSON.stringify({
          schema: "777-desktop-draft-v1",
          details: draft.details,
          lines: draft.lines,
        }),
      );
    } catch {
      setFeedback("当前草稿无法保存到本机，请保持窗口打开。");
      setIsError(true);
    }
  }, [draft.details, draft.lines]);
  const run = useCallback(
    async <T>(work: () => Promise<T>, done?: (v: T) => void) => {
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
        if (current === epoch.current) {
          setFeedback(errorMessage(e));
          setIsError(true);
          const code = errorCode(e);
          if (
            ["COMMIT_UNKNOWN", "PENDING_REQUEST_REQUIRES_QUERY"].includes(code)
          )
            setPending(true);
          if (code === "UNAUTHENTICATED") {
            epoch.current++;
            setSession(null);
            setSelected(null);
            setCatalog(null);
            setListing(null);
            setJobs([]);
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
    request<{ connection: Connection | null; pending: boolean }>("connection")
      .then((r) => {
        setConnection(r.connection);
        setPending(r.pending);
      })
      .catch((e) => {
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
      setJobs([]);
      setBackup(null);
      setPreferences(null);
      dispatch({ type: "invalidate" });
      setFeedback(`${message}登录已失效，请重新登录后读取。`);
    }
  }
  async function connect(c: Connection, username: string, password: string) {
    await run(
      async () => {
        const s = await request<Session>("connect", {
          connection: c,
          username,
          password,
        });
        const p = await request<Catalog>("prices");
        const dirs = await request<Preferences>("settings");
        return { s, p, dirs };
      },
      ({ s, p, dirs }) => {
        epoch.current++;
        setConnection(c);
        setSession(s);
        setPending(s.pending);
        setCatalog(p);
        setPreferences(dirs);
        dispatch({ type: "prices", version: p.price_version_id });
        setRoute("quote");
      },
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
  const refreshPrices = () =>
    run(
      () => request<Catalog>("prices"),
      (p) => {
        setCatalog(p);
        dispatch({ type: "prices", version: p.price_version_id });
        setFeedback("价格已刷新，请重新计算并核对。");
      },
    );
  const calculate = () => {
    const revision = draft.revision;
    return run(
      () =>
        request<{ draft_revision: string; result: Calculation }>("calculate", {
          snapshot: snapshot(draft),
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
    const submitted = snapshot(draft),
      details = draft.details;
    return run(
      async () => {
        const receipt = await request<{ order_id: string }>("submit", {
          snapshot: submitted,
          details,
          draft_revision: draft.revision,
        });
        return afterSaved(() =>
          request<Order>("order", { order_id: receipt.order_id }),
        );
      },
      (r) => {
        setPending(false);
        dispatch({ type: "committed", snapshot: submitted, details });
        setSelected(r.value);
        setListing(null);
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
    () =>
      run(
        () => request<{ jobs: Job[] }>("outputs"),
        (v) => setJobs(v.jobs),
      ),
    [run],
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
        return afterSaved(() => request<{ jobs: Job[] }>("outputs"));
      },
      (r) => {
        setJobs(r.value?.jobs ?? []);
        setRoute("tasks");
        savedFeedback(r, "输出任务已创建，订单不会重复入账。");
      },
    );
  const retryOutput = (id: string) =>
    run(
      async () => {
        await request("retry_output", { job_id: id });
        return afterSaved(() => request<{ jobs: Job[] }>("outputs"));
      },
      (r) => {
        setJobs(r.value?.jobs ?? []);
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
          submitted?: { snapshot: unknown; details: unknown };
        }>("recover", { retry }),
      (v) => {
        setPending(v.pending);
        if (!v.pending && v.result) {
          setFeedback("原请求已确认保存。");
          if (v.path === "/v1/orders") {
            if (v.submitted)
              dispatch({
                type: "committed",
                snapshot: v.submitted.snapshot,
                details: v.submitted.details,
              });
            else dispatch({ type: "invalidate" });
          }
          setListing(null);
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
  const makeBackup = () =>
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
          setJobs([]);
          setBackup(null);
          setPreferences(null);
          dispatch({ type: "invalidate" });
        }
      },
      () => {},
    );
  function navigate(next: Route) {
    setRoute(next);
    if (next === "orders" || next === "profit")
      void loadOrders({ ...filters, view: "" });
    if (next === "tasks") void loadJobs();
    if (next === "settings") void loadSettings();
  }
  return {
    listScrollRef,
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
    output,
    retryOutput,
    recover,
    loadSettings,
    saveSettings,
    makeBackup,
    logout,
  };
}
export type Workbench = ReturnType<typeof useWorkbench>;
