import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const quelle = readFileSync(new URL('../templates/_whatsapp_sync_script.html', import.meta.url), 'utf8');
const anfang = {autorisiert: true, technisch_bereit: false, schritte: [
  {art: 'history', zustand: 'offen', meldung: 'Noch nicht angefordert.', fortschritt: 0, startbar: true}]};
function seite(fetch) {
  const elemente = new Map();
  const erstellen = () => ({disabled: false, kinder: [], textContent: '', ereignisse: {},
    replaceChildren() {this.kinder = [];}, appendChild(k) {this.kinder.push(k);},
    addEventListener(n, f) {this.ereignisse[n] = f;}});
  const document = {getElementById(id) {if (!elemente.has(id)) elemente.set(id, erstellen()); return elemente.get(id);},
    createElement: erstellen, createTextNode: text => ({textContent: text})};
  const c = vm.createContext({document, fetch});
  vm.runInContext(quelle, c);
  c.starteSynchronisierung('werkstatt-synthetisch', anfang);
  return {element: id => elemente.get(id), text: () => elemente.get('sync-status').kinder.map(k => k.textContent).join(' ')};
}
const warten = () => new Promise(r => setImmediate(r));

test('Annahme zeigt keinen Abschluss und keine betriebliche Freigabe', async () => {
  const s = seite(async () => ({ok:true, json:async () => ({...anfang, schritte:[{
    art:'history', zustand:'angenommen', meldung:'Anforderung angenommen.', fortschritt:0, startbar:false}]})}));
  s.element('sync-start').ereignisse.click(); await warten();
  assert.match(s.text(), /noch nicht bereit/);
  assert.match(s.text(), /Automatikfreigabe bleibt geschlossen/);
  assert.equal(s.element('sync-verzicht').disabled, true);
});

test('Technische Bereitschaft behauptet keine vollständige Kontaktliste', async () => {
  const s = seite(async () => ({ok:true, json:async () => ({...anfang, technisch_bereit:true})}));
  s.element('sync-pruefen').ereignisse.click(); await warten();
  assert.match(s.text(), /Vollständigkeit.*nicht nachgewiesen/);
  assert.match(s.text(), /Automatikfreigabe bleibt geschlossen/);
});

test('Späte Statusantwort überschreibt keine neuere Entscheidung', async () => {
  const offen = [];
  const s = seite(() => new Promise(resolve => offen.push(resolve)));
  s.element('sync-pruefen').ereignisse.click();
  s.element('sync-pruefen').ereignisse.click();
  offen[1]({ok:true,json:async()=>({...anfang, schritte:[{art:'history',meldung:'Verlauf nicht geteilt.',fortschritt:0}]})});
  await warten();
  offen[0]({ok:true,json:async()=>anfang}); await warten();
  assert.match(s.text(), /nicht geteilt/);
  assert.doesNotMatch(s.text(), /Noch nicht angefordert/);
});

test('Lokaler Verzicht sendet nur die Werkstatt und kein erfundenes Consent-Feld', async () => {
  let anfrage;
  const s = seite(async (url, optionen) => {anfrage={url,optionen}; return {ok:true,json:async()=>anfang};});
  s.element('sync-verzicht').ereignisse.click(); await warten();
  assert.match(anfrage.url, /\/verzicht$/);
  assert.deepEqual(JSON.parse(anfrage.optionen.body), {workshop_id:'werkstatt-synthetisch'});
});
