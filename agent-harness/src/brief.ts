// A tool call's arguments, short enough to show and to keep: shared by the live view and the extension receipts.
const cut = (value: any, limit: number) => typeof value === 'string' && value.length > limit ? value.slice(0, limit) + '…' : value;
const plain = (value: any) => value === null || ['string', 'number', 'boolean'].includes(typeof value);
/** A tool call's arguments, short enough to show: long texts are cut and deep values left out. */
export function brief(args: any) {
  if (!args || typeof args !== 'object' || Array.isArray(args)) return {};
  const result: Record<string, any> = {};
  for (const [key, value] of Object.entries(args).slice(0, 12)) {
    if (plain(value)) result[key] = cut(value, 200);
    else if (Array.isArray(value)) result[key] = value.filter(plain).slice(0, 6).map(item => cut(item, 80));
    else if (value && typeof value === 'object') result[key] = Object.fromEntries(Object.entries(value).filter(([, item]) => plain(item)).slice(0, 8).map(([name, item]) => [name, cut(item, 120)]));
  }
  return result;
}
