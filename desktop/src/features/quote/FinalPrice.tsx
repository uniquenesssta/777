import { Input } from "../../ui/components";
import { money } from "../../state/format";
import "./final-price.css";
export function FinalPrice({value, calculated, disabled, valid, onChange}: {
  value: string; calculated?: string; disabled: boolean; valid: boolean; onChange: (value: string) => void;
}) {
  return <div className="final-price" data-node-id="171:2355">
    <label htmlFor="final-price">最终成交价</label>
    <Input id="final-price" inputMode="decimal" maxLength={32} value={value}
      placeholder={calculated === undefined ? "—" : money(calculated, false)}
      disabled={disabled} aria-invalid={!valid} aria-describedby={valid ? undefined : "final-price-error"}
      onChange={e => onChange(e.target.value)} />
    {!valid && <small id="final-price-error" role="alert">请输入有效的非负金额，最多两位小数。</small>}
  </div>;
}
