import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

async function module(path) {
  const source = await readFile(new URL(path, import.meta.url), 'utf8');
  return import(`data:text/javascript;base64,${Buffer.from(ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ES2022 } }).outputText).toString('base64')}`);
}
const format = await module('../src/services/format.ts');
const { createTabIdentity } = await module('../src/services/session.ts');
process.env.TZ = 'America/Argentina/Buenos_Aires';

test('horas locales, offsets equivalentes y fechas de calendario sin desfase', () => {
  assert.match(format.formatDateTime('2026-10-31T01:30:00Z'), /30\/10\/26.*22:30:00/);
  assert.equal(format.formatDateTime('2026-10-31T01:30:00'), format.formatDateTime('2026-10-30T22:30:00-03:00'));
  assert.equal(format.formatCalendarDate('2026-10-31'), '31/10/2026');
  assert.equal(format.formatCalendarDate('2026-11-01'), '01/11/2026');
  assert.equal(format.formatAlertDescription('Observado 2026-10-31T01:30:00+00:00; referencia 2026-10-24'), `Observado ${format.formatDateTime('2026-10-31T01:30:00Z')}; referencia 24/10/2026`);
});
test('distancias e importes: dos decimales, redondeo visual y precisión decimal', () => {
  assert.equal(format.formatDistance('0.1'), '0,10');
  assert.equal(format.formatDistance('5'), '5,00');
  assert.equal(format.formatMoney('1234.5'), '$ 1.234,50');
  assert.equal(format.formatMoney('-10.99'), '$ -10,99');
  assert.equal(format.formatMoney('9999999999999999.99'), '$ 9.999.999.999.999.999,99');
  assert.equal(format.formatMoney('1.999'), '$ 2,00');
});

test('el día mostrado coincide con Buenos Aires aunque el navegador use otro huso', () => {
  const previous = process.env.TZ;
  try {
    process.env.TZ = 'UTC';
    assert.match(format.formatDateTime('2026-11-01T02:59:59Z'), /31\/10\/26.*23:59:59/);
    assert.match(format.formatDateTime('2026-11-01T03:00:00Z'), /1\/11\/26.*00:00:00/);
  } finally { process.env.TZ = previous; }
});

function storage(initial) {
  const values = new Map(initial ? [['oliva.tab', initial]] : []);
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), values };
}
function locks() {
  const held = new Set();
  return { request: async (name, options, callback) => {
    if (held.has(name)) return callback(null);
    held.add(name);
    try { return await callback({ name }); } finally { held.delete(name); }
  } };
}
test('pestañas nuevas y duplicadas tienen identificadores distintos; recarga conserva el propio', async () => {
  const manager = locks(), first = storage(), second = storage();
  let releaseA, releaseB, releaseClone;
  const a = createTabIdentity(first, manager, (dispose) => { releaseA = dispose; }, () => 'a'.repeat(32));
  const b = createTabIdentity(second, manager, (dispose) => { releaseB = dispose; }, () => 'b'.repeat(32));
  assert.equal(await a(), 'a'.repeat(32)); assert.equal(await a(), await a());
  assert.equal(await b(), 'b'.repeat(32));
  const clone = storage(await a());
  const c = createTabIdentity(clone, manager, (dispose) => { releaseClone = dispose; }, () => 'c'.repeat(32));
  assert.equal(await c(), 'c'.repeat(32));
  releaseA(); await new Promise((resolve) => setImmediate(resolve));
  const reloaded = createTabIdentity(first, manager, (dispose) => { releaseA = dispose; }, () => 'd'.repeat(32));
  assert.equal(await reloaded(), 'a'.repeat(32));
  assert.deepEqual([...first.values.keys()], ['oliva.tab']);
  releaseA(); releaseB(); releaseClone();
});
test('sin Web Locks se conserva identidad al recargar y se reemplazan identificadores inválidos', async () => {
  const store = storage('token-no-valido');
  const a = createTabIdentity(store, undefined, () => {}, () => 'e'.repeat(32));
  assert.equal(await a(), 'e'.repeat(32));
  const reload = createTabIdentity(store, undefined, () => {}, () => 'f'.repeat(32));
  assert.equal(await reload(), await a());
});
