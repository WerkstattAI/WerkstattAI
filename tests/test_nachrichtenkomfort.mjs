import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {test} from 'node:test';
import vm from 'node:vm';

const code = readFileSync(new URL('../static/arbeitsplatz/nachrichtenkomfort.js', import.meta.url), 'utf8');
function vorschau() {
  const events = {}, bildEvents = {}, buttonEvents = {};
  let position = 0;
  const verlauf = {
    scrollHeight:1000, clientHeight:300,
    get scrollTop() { return position; },
    set scrollTop(value) { position = Math.min(value, this.scrollHeight - this.clientHeight); },
    addEventListener: (name, fn) => events[name] = fn,
    querySelectorAll: () => [{addEventListener: (name, fn) => bildEvents[name] = fn}],
    focus() { this.focused = true; },
  };
  const navigation = {hidden:true};
  const button = {addEventListener: (name, fn) => buttonEvents[name] = fn};
  vm.runInNewContext(code, {document:{
    addEventListener() {}, getElementById: () => verlauf,
    querySelector: name => name === '.verlauf-navigation' ? navigation : button,
  }});
  return {verlauf, navigation, events, bildEvents, buttonEvents};
}

test('Start und nachgeladenes Bild zeigen die neueste Nachricht', () => {
  const f = vorschau();
  assert.equal(f.verlauf.scrollTop, 700);
  f.verlauf.scrollHeight += 200;
  f.bildEvents.load();
  assert.equal(f.verlauf.scrollTop, 900);
  assert.equal(f.navigation.hidden, true);
});

test('Ältere Nachrichten bleiben beim Laden und Bildfehler an ihrer Position', () => {
  const f = vorschau();
  f.verlauf.scrollTop = 100;
  f.events.scroll();
  assert.equal(f.navigation.hidden, false);
  f.verlauf.scrollHeight += 200;
  f.bildEvents.load();
  f.bildEvents.error();
  assert.equal(f.verlauf.scrollTop, 100);
  f.buttonEvents.click();
  assert.equal(f.verlauf.scrollTop, 900);
  assert.equal(f.navigation.hidden, true);
  assert.equal(f.verlauf.focused, true);
});

test('Andere Seiten ohne WhatsApp-Verlauf bleiben funktionsfähig', () => {
  assert.doesNotThrow(() => vm.runInNewContext(code, {document:{
    addEventListener() {}, getElementById: () => null, querySelector: () => null,
  }}));
});
