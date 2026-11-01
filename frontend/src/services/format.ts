/** Instantes del servidor en horario local; las fechas de calendario no son instantes. */
export function timestamp(value: string): Date {
  return new Date(/[zZ]$|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`);
}
export function formatDateTime(value: string): string {
  return timestamp(value).toLocaleString('es-AR', { timeZone: 'America/Argentina/Buenos_Aires', dateStyle: 'short', timeStyle: 'medium', hour12: false });
}
export function formatCalendarDate(value: string): string {
  const [year, month, day] = value.split('-');
  return `${day}/${month}/${year}`;
}
export function localDate(offset = 0): string {
  const date = new Date(); date.setDate(date.getDate() + offset);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}
export function formatDistance(value: string): string {
  return Number(value).toLocaleString('es-AR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
export function formatMoney(value: string): string {
  // Decimal exacto: no pierde precisión de importes grandes al convertirlos a Number.
  const negative = value.startsWith('-');
  const [integer, fraction = ''] = value.replace(/^[+-]/, '').split('.');
  let cents = BigInt(integer || '0') * 100n + BigInt(fraction.padEnd(2, '0').slice(0, 2));
  if (Number(fraction[2] ?? '0') >= 5) cents += 1n;
  return `$ ${negative && cents !== 0n ? '-' : ''}${(cents / 100n).toLocaleString('es-AR')},${String(cents % 100n).padStart(2, '0')}`;
}
export function formatAlertDescription(value: string): string {
  return value.replace(/\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})/g, formatDateTime)
    .replace(/\b\d{4}-\d{2}-\d{2}\b/g, formatCalendarDate);
}
