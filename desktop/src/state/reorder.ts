import type { DraftLine } from './draft';

// Move the original object: source IDs and frozen prices must travel with it.
export function moveLine(lines: DraftLine[], id: string, target: number): DraftLine[] {
  const from = lines.findIndex(line => line.id === id);
  if (from < 0 || target < 0 || target >= lines.length || from === target) return lines;
  const next = [...lines];
  const [line] = next.splice(from, 1);
  next.splice(target, 0, line);
  return next;
}
