export function money(raw: string | undefined | null, group = true): string {
  if (raw === undefined || raw === null || !/^-?\d+$/.test(raw)) return "—";
  const negative = raw.startsWith("-");
  const n = BigInt(raw);
  const digits = (n < 0n ? -n : n).toString().padStart(3, "0");
  let major = digits.slice(0, -2);
  if (group) major = major.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${negative && n !== 0n ? "-" : ""}${major}.${digits.slice(-2)}`;
}
export function stamp(raw: string) {
  return raw ? raw.replace("T", " ").replace("Z", "").slice(0, 16) : "—";
}
