// Render the actual submitted-order component; no native IPC or Host stand-in here.
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { allowed, type Permission } from "../../../src/state/permissions";
import { DetailPage } from "../../../src/features/DetailPage";
import type { Workbench } from "../../../src/state/useWorkbench";

export function detailMarkup(busy: boolean, role = "admin") {
  const app = {
    busy, pending: false, session: { role }, can:(id:Permission)=>allowed(null,role,id),
    selected: { details: { customer: "isolated", order_ref: "native-idle", wechat: "" },
      state: "active", created_at: "2026-10-14T00:00:00Z", lines: [], notes: [],
      income_cents: "1000", cost_cents: "400", profit_cents: "600" },
  } as unknown as Workbench;
  return renderToStaticMarkup(createElement("main", { className: "workspace", "aria-busy": busy },
    createElement(DetailPage, { app })));
}
