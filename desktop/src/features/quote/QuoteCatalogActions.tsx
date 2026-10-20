import type { Workbench } from "../../state/useWorkbench";
import "./quoteCatalogActions.css";
import { priceVersionLabel } from "../../state/priceVersion";
import { Button, Icon } from "../../ui/components";

export function QuoteCatalogActions({app}:{app:Workbench}) {
  const date = priceVersionLabel(app.catalog?.published_at, app.catalog?.publication_sequence);
  return <div className="section-actions quote-catalog-actions">
    <Button variant="ghost" className="price-version" onClick={()=>void app.refreshPrices()} disabled={app.busy}>
      <Icon name="check" />
      {date ? `价格版本 ${date}` : app.catalog ? "刷新价格" : "价格未连接"}
    </Button>
    <Button variant="outline" disabled={app.working || app.pending} onClick={app.clearQuote}>一键清除</Button>
  </div>;
}
