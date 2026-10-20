/** Display the publication day, never the current day or the internal version ID. */
export function priceVersionDate(publishedAt?: string): string | null {
  if (!publishedAt || !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(publishedAt)) return null;
  const date = new Date(publishedAt);
  if (!Number.isFinite(date.getTime())) return null;
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: "Asia/Shanghai", year: "2-digit", month: "2-digit", day: "2-digit",
  }).formatToParts(date);
  return ["year", "month", "day"].map(type => parts.find(p => p.type === type)!.value).join("");
}

export function priceVersionLabel(publishedAt?: string, sequence?: string): string | null {
  const date = priceVersionDate(publishedAt);
  return date && sequence && /^[1-9]\d*$/.test(sequence) ? `${date}-${sequence}` : null;
}
