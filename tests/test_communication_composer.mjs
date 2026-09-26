import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../templates/_communication_script.html", import.meta.url), "utf8");

class Field {
  constructor(value = "") { this.value = value; this.listeners = new Map(); this.options = []; }
  addEventListener(name, callback) { this.listeners.set(name, callback); }
  change(name = "change") { this.listeners.get(name)?.(); }
  replaceChildren(...options) { this.options = options; }
  add(option) { this.options.push(option); }
  querySelector(selector) { return this.options.find(option => selector.includes(`'${option.value}'`)); }
}

function fixture(storage = new Map(), text = "Nachricht an den Kunden") {
  const purpose = new Field();
  purpose.options = ["", "workshop_answer", "workshop_question", "workshop_notification"].map(value => ({value, disabled: value === ""}));
  const target = new Field();
  const targetField = {};
  const help = {};
  const messageId = new Field();
  const textarea = new Field(text);
  const fields = {"[data-message-purpose]": purpose, "[data-reply-target]": target,
    "[data-reply-target-field]": targetField, "[data-purpose-help]": help,
    "[data-client-message-id]": messageId, textarea};
  let sequence = 0;
  const factory = vm.runInNewContext(source + "\ncommunicationComposer", {
    window: {crypto: {randomUUID: () => `id-${storage.size}-${++sequence}`}, sessionStorage: {
      setItem: (key, value) => storage.set(key, value), getItem: key => storage.get(key), removeItem: key => storage.delete(key)
    }}, Option: class {constructor(text, value) {this.text = text; this.value = value;}},
  });
  const controller = factory({querySelector: selector => fields[selector]});
  return {purpose, target, targetField, help, messageId, textarea, controller, storage};
}

const questions = [{message_id: "customer-one", text: "Wie lange dauert die Reparatur?"},
  {message_id: "customer-two", text: "Was kostet sie?"}];

test("without an open question, information is selected and no answer target is submitted", () => {
  const form = fixture();
  form.controller.configure([], "ticket:one", false);
  assert.equal(form.purpose.value, "workshop_notification");
  assert.equal(form.target.disabled, true);
  assert.equal(form.target.required, false);
  assert.equal(form.targetField.hidden, true);
});

test("one open question is selected, multiple questions require explicit selection", () => {
  const form = fixture();
  form.controller.configure(questions.slice(0, 1), "ticket:one", false);
  assert.equal(form.target.value, "customer-one");
  assert.equal(form.target.required, true);
  form.controller.configure(questions, "ticket:two", false);
  assert.equal(form.target.value, "");
  assert.equal(form.target.required, true);
});

test("workshop questions and notifications never submit an old answer target", () => {
  const form = fixture();
  form.controller.configure(questions.slice(0, 1), "ticket:one", false);
  for (const purpose of ["workshop_question", "workshop_notification"]) {
    form.purpose.value = purpose;
    form.purpose.change();
    assert.equal(form.target.disabled, true);
    assert.equal(form.target.required, false);
  }
});

test("an unanswered target picker remains required after reloading a multiple-question draft", () => {
  const first = fixture();
  first.controller.configure(questions, "ticket:one", false);
  const revisit = fixture(first.storage);
  revisit.controller.configure(questions, "ticket:one", false);
  assert.equal(revisit.purpose.value, "workshop_answer");
  assert.equal(revisit.target.value, "");
  assert.equal(revisit.target.required, true);
  assert.equal(revisit.targetField.hidden, false);
});

test("unchanged retry retains its message ID; an edited message gets a new ID", () => {
  const first = fixture();
  first.controller.configure(questions.slice(0, 1), "ticket:one", false);
  const originalId = first.messageId.value;
  const retry = fixture(first.storage);
  retry.controller.configure(questions.slice(0, 1), "ticket:one", false);
  assert.equal(retry.messageId.value, originalId);
  retry.textarea.value = "Geänderter Text";
  retry.textarea.change("input");
  assert.notEqual(retry.messageId.value, originalId);
});

test("a resolved draft target cannot silently turn an answer into a notification", () => {
  const first = fixture();
  first.controller.configure(questions.slice(0, 1), "ticket:one", false);
  const revisit = fixture(first.storage);
  revisit.controller.configure([], "ticket:one", false);
  assert.equal(revisit.purpose.value, "");
  assert.equal(revisit.target.value, "");
  assert.match(revisit.help.textContent, /wählen/);
});

test("confirmed successful sends clear prior purpose and reply-target metadata", () => {
  const form = fixture();
  form.controller.configure(questions.slice(0, 1), "ticket:one", false);
  form.purpose.value = "workshop_question";
  form.purpose.change();
  form.controller.configure([], "ticket:one", true);
  assert.equal(form.purpose.value, "workshop_notification");
  assert.equal(form.target.value, "");
});
