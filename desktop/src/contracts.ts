export type Role = "admin" | "sales";
export interface Session {
  ledger_id?: string | null;
  pricing_mode_version?: string | null;
  subject: string;
  role: Role;
  username: string;
  pending: boolean;
}
export interface Connection {
  url: string;
  certificate_pem: string;
  certificate_sha256: string;
}
export interface Price {
  product_id: string;
  sale: string;
  cost?: string;
  k: string;
  single: boolean;
  pricing_mode?: "manual" | "cost_plus";
  unit_sale?: string;
}
export interface Catalog {
  pricing_mode_version?: "final-unit-v1";
  price_version_id: string;
  items: Price[];
  rule_version: string;
  numeric_profile: string;
}
export type RawLine =
  | {
      line_kind: "normal";
      product_id: string;
      h: string;
      w: string;
      q: string;
      name: string;
    }
  | { line_kind: "discount"; percent: string; name: string };
export interface Line extends Record<string, unknown> {
  line_id?: string;
  sequence: number;
  raw: RawLine;
  normalized: Record<string, string>;
  income_cents: string;
  cost_cents?: string;
  profit_cents?: string;
  subtotal_before_cents: string;
}
export interface Money {
  income_cents: string;
  cost_cents?: string;
  profit_cents?: string;
  financial_display?: {
    income: string;
    cost: string;
    profit: string;
    margin: string | null;
  };
}
export interface Calculation {
  status: string;
  price_version_id: string;
  lines: Line[];
  totals: Money | null;
  issues: { reason: string; field: string; line_index: number | null }[];
  warnings: unknown[];
}
export interface CustomerChoice { customer_id?: string; anchor_order_id?: string; new_customer?: boolean }
export interface CustomerGroup { group_id:string; details:Order["details"]; orders:Order[]; total:number; active_count:number; totals:Money; order_offset:number }
export interface CustomerListing { groups:CustomerGroup[]; total:number; offset:number; limit:number }
export interface Order extends Money {
  customer_id?: string | null;
  history?: {revision:string;created_at:string;details:Order["details"];income_cents:string;cost_cents?:string;profit_cents?:string}[];
  order_id: string;
  revision: string;
  state: "active" | "void";
  created_at: string;
  details: { customer: string; order_ref: string; wechat: string };
  lines: Line[];
  notes: {
    note_id: string;
    author: string;
    body: string;
    created_at: string;
  }[];
  price_version_id: string;
  owner_id?: string;
}
export interface Listing {
  orders: Order[];
  offset: number;
  limit: number;
  total: number;
  totals: Money;
  view: string;
  next_cursor: string | null;
}
export interface Preferences {
  revision: string;
  export_dir: string;
  image_dir: string;
}
export interface OrderChanges {
  revision: string; to_revision: string; created_at: string;
  changes: {section:string;field:string;before:string|null;after:string|null;format:"text"|"money"}[];
}
export interface JobListing {has_more?:boolean;jobs:Job[];offset:number;total:number;limit:number}
export interface Job {
  batch?:{id:string;part:number;count:number;from:string;to:string;order_count:number}|null;
  range?:{from:string;to:string};
  job_id: string;
  order_id: string;
  kind: string;
  state: string;
  error?: string;
  filename?: string;
  created_at: string;
}

export type AnalysisPeriod = "day" | "week" | "month" | "year";
export interface AnalysisFilters {
  period: AnalysisPeriod;
  from: string;
  to: string;
}
export interface AnalysisTotals extends Money {
  cost_cents: string;
  profit_cents: string;
  order_count: number;
  margin: string | null;
}
export interface ProfitAnalysis extends AnalysisFilters {
  format: "777-profit-analysis-v1";
  timezone: string;
  ledger_revision: string;
  unplaced_date_orders: number;
  totals: AnalysisTotals;
  buckets: {
    start: string;
    totals: AnalysisTotals;
    profit_ohlc?: ProfitOHLC;
  }[];
}
export interface ProfitOHLC {
  open_cents: string;
  high_cents: string;
  low_cents: string;
  close_cents: string;
}
