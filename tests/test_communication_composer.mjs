import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import {test} from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../templates/_communication_script.html", import.meta.url), "utf8");
let generatedIds = 0;

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
  const factory = vm.runInNewContext(source + "\ncommunicationComposer", {
    window: {crypto: {randomUUID: () => `id-${++generatedIds}`}, sessionStorage: {
      setItem: (key, value) => storage.set(key, value), getItem: key => storage.get(key), removeItem: key => storage.delete(key)
    }}, Option: class {constructor(text, value) {this.text = text; this.value = value;}},
  });
  const events = new Map();
  const controller = factory({querySelector: selector => fields[selector], addEventListener: (name, callback) => events.set(name, callback)});
  function submit(action = null, prevented = false) {
    const event = {defaultPrevented: prevented, submitter: {getAttribute: () => action},
      preventDefault() { this.defaultPrevented = true; }};
    events.get("submit")(event);
    return event;
  }
  return {purpose, target, targetField, help, messageId, textarea, controller, storage, submit};
}

const questions = [{message_id: "customer-one", text: "Wie lange dauert die Reparatur?"},
  {message_id: "customer-two", text: "Was kostet sie?"}];

function choose(form, purpose = "workshop_answer", target = "customer-one") {
  form.purpose.value = purpose;
  form.purpose.change();
  if (purpose === "workshop_answer" && target) {
    form.target.value = target;
    form.target.change();
  }
}

test("without an open question, purpose must still be deliberately selected", () => {
  const form = fixture();
  form.controller.configure([], "ticket:one", false);
  assert.equal(form.purpose.value, "");
  assert.equal(form.target.disabled, true);
  assert.equal(form.target.required, false);
  assert.equal(form.targetField.hidden, true);
  assert.equal(form.submit().defaultPrevented, true);
  choose(form, "workshop_notification");
  assert.equal(form.submit().defaultPrevented, false);
});

test("one or multiple questions require explicit purpose and target selection", () => {
  const form = fixture();
  for (const available of [questions.slice(0, 1), questions]) {
    form.controller.configure(available, "ticket:fresh", true);
    assert.equal(form.purpose.value, "");
    assert.equal(form.target.value, "");
    assert.equal(form.submit().defaultPrevented, true);
    choose(form, "workshop_answer", "");
    assert.equal(form.target.required, true);
    assert.equal(form.submit().defaultPrevented, true);
    form.target.value = "customer-one";
    form.target.change();
    assert.equal(form.submit().defaultPrevented, false);
  }
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
  choose(first, "workshop_answer", "");
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
  choose(first);
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
  choose(first);
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
  assert.equal(form.purpose.value, "");
  assert.equal(form.target.value, "");
});

test("failed retry preserves text, purpose and question target, renewing ID only on deliberate submit", () => {
  const first = fixture();
  first.controller.configure(questions, "ticket:failed", false);
  choose(first, "workshop_answer", "");
  first.target.value = "customer-two";
  first.target.change();
  const failedId = first.messageId.value;
  const retry = fixture(first.storage);
  retry.controller.configure(questions, "ticket:failed", false, {resultStatus: "failed"});
  assert.equal(retry.messageId.value, failedId, "loading must not create a new attempt");
  assert.equal(retry.textarea.value, first.textarea.value);
  assert.equal(retry.purpose.value, "workshop_answer");
  assert.equal(retry.target.value, "customer-two");
  retry.submit();
  assert.notEqual(retry.messageId.value, failedId);
  const newId = retry.messageId.value;
  retry.submit();
  assert.equal(retry.messageId.value, newId, "a repeated submit uses the same new attempt");
});

test("opening external WhatsApp or cancelling submission does not consume the failed retry", () => {
  const first = fixture();
  first.controller.configure(questions.slice(0, 1), "ticket:failed", false);
  choose(first);
  const failedId = first.messageId.value;
  const retry = fixture(first.storage);
  retry.controller.configure(questions.slice(0, 1), "ticket:failed", false, {resultStatus: "failed"});
  retry.submit("/dashboard/whatsapp/open-manual");
  retry.submit(null, true);
  assert.equal(retry.messageId.value, failedId);
  retry.submit();
  assert.notEqual(retry.messageId.value, failedId);
});

test("unknown, pending and sending keep identity and block submission even after text edits", () => {
  for (const status of ["unknown", "pending", "sending"]) {
    const first = fixture();
    first.controller.configure(questions.slice(0, 1), "ticket:uncertain", false);
    choose(first);
    const originalId = first.messageId.value;
    const retry = fixture(first.storage);
    retry.controller.configure(questions.slice(0, 1), "ticket:uncertain", false, {resultStatus: status});
    retry.textarea.value = "Geänderter Entwurf während der Klärung";
    retry.textarea.change("input");
    assert.equal(retry.messageId.value, originalId);
    assert.equal(retry.submit().defaultPrevented, true);
    assert.equal(retry.messageId.value, originalId);
  }
});

test("a server-side conversation lock takes precedence over a failed retry redirect", () => {
  const form = fixture();
  form.controller.configure(questions, "ticket:blocked", false, {resultStatus: "failed", dispatchBlocked: true});
  const originalId = form.messageId.value;
  assert.equal(form.submit().defaultPrevented, true);
  assert.equal(form.messageId.value, originalId);
});

test("legacy drafts retain text but must reselect purpose and target", () => {
  const storage = new Map([["ticket:old:communication", JSON.stringify({
    purpose: "workshop_answer", reply_to_message_id: "customer-one", message_id: "legacy-id", text: "Alter Text"
  })]]);
  const form = fixture(storage, "");
  form.controller.configure(questions, "ticket:old", false, {resultStatus: "failed"});
  assert.equal(form.textarea.value, "Alter Text");
  assert.equal(form.purpose.value, "");
  assert.equal(form.target.value, "");
  assert.equal(form.submit().defaultPrevented, true);
  assert.equal(form.messageId.value, "legacy-id");
  choose(form);
  assert.equal(form.messageId.value, "legacy-id");
  assert.equal(form.submit().defaultPrevented, false);
  assert.notEqual(form.messageId.value, "legacy-id");
});

test("all deliberately chosen purposes survive draft restoration", () => {
  for (const purpose of ["workshop_answer", "workshop_question", "workshop_notification"]) {
    const first = fixture();
    first.controller.configure(questions, "ticket:chosen", false);
    choose(first, purpose);
    const revisit = fixture(first.storage);
    revisit.controller.configure(questions, "ticket:chosen", false);
    assert.equal(revisit.purpose.value, purpose);
    assert.equal(revisit.target.value, purpose === "workshop_answer" ? "customer-one" : "");
    assert.equal(revisit.messageId.value, first.messageId.value);
    assert.equal(revisit.submit().defaultPrevented, false);
  }
});

test("a closed target requires reselection even when another question remains", () => {
  const first = fixture();
  first.controller.configure(questions, "ticket:closed", false);
  choose(first);
  const revisit = fixture(first.storage);
  revisit.controller.configure(questions.slice(1), "ticket:closed", false);
  assert.equal(revisit.textarea.value, first.textarea.value);
  assert.equal(revisit.purpose.value, "");
  assert.equal(revisit.target.value, "");
  assert.equal(revisit.submit().defaultPrevented, true);
});

test("failed retry edits retain identity until a valid deliberate send", () => {
  const first = fixture();
  first.controller.configure(questions, "ticket:edit-failed", false);
  choose(first);
  const failedId = first.messageId.value;
  const retry = fixture(first.storage);
  retry.controller.configure(questions, "ticket:edit-failed", false, {resultStatus: "failed"});
  retry.textarea.value = "Korrigierter Text";
  retry.textarea.change("input");
  choose(retry, "workshop_answer", "");
  assert.equal(retry.submit().defaultPrevented, true);
  assert.equal(retry.messageId.value, failedId);
  retry.target.value = "customer-two";
  retry.target.change();
  assert.equal(retry.messageId.value, failedId);
  retry.submit();
  assert.notEqual(retry.messageId.value, failedId);
});

test("web chat answer help describes saving rather than delivery", () => {
  const form = fixture();
  form.help.dataset = {answerHelp: "Diese Antwort schließt die ausgewählte Kundenfrage beim Speichern für den Web-Chat."};
  form.controller.configure(questions, "ticket:web", false);
  choose(form);
  assert.match(form.help.textContent, /beim Speichern für den Web-Chat/);
});

function simpleFixture(storage = new Map()) {
  const messageId = new Field();
  const phone = new Field("491701234567");
  const textarea = new Field("Unveränderter Testtext");
  const fields = {"input[name='message_id']": messageId, "input[name='customer_phone']": phone, textarea};
  const events = new Map();
  const form = {dataset: {}, querySelector: selector => fields[selector], getAttribute: () => "/dashboard/whatsapp/test",
    addEventListener: (name, callback) => events.set(name, callback)};
  const factory = vm.runInNewContext(source + "\nsimpleDispatchAttempt", {window: {
    crypto: {randomUUID: () => `simple-${++generatedIds}`}, sessionStorage: {
      setItem: (key, value) => storage.set(key, value), getItem: key => storage.get(key), removeItem: key => storage.delete(key)
    }
  }});
  const controller = factory(form);
  function submit(action = null) {
    const event = {defaultPrevented: false, submitter: {getAttribute: () => action}, preventDefault() {this.defaultPrevented = true;}};
    events.get("submit")(event);
    return event;
  }
  return {form, messageId, phone, textarea, storage, controller, submit};
}

test("diagnostic and template failed attempts preserve their draft and obtain a new ID on click", () => {
  for (const action of [null, "/dashboard/whatsapp/start-template"]) {
    const first = simpleFixture();
    first.controller.configure("test:failed");
    first.submit(action);
    const failedId = first.messageId.value;
    const retry = simpleFixture(first.storage);
    retry.phone.value = "";
    retry.textarea.value = "";
    retry.controller.configure("test:failed", {resultStatus: "failed", restoreFields: true});
    assert.equal(retry.messageId.value, failedId);
    assert.equal(retry.phone.value, first.phone.value);
    assert.equal(retry.textarea.value, first.textarea.value);
    retry.submit(action);
    assert.notEqual(retry.messageId.value, failedId);
    const retryId = retry.messageId.value;
    retry.submit(action);
    assert.equal(retry.messageId.value, retryId);
  }
});

test("diagnostic and template unknown attempts stay blocked with the original ID", () => {
  const first = simpleFixture();
  first.controller.configure("test:unknown");
  first.submit();
  const originalId = first.messageId.value;
  const revisit = simpleFixture(first.storage);
  revisit.controller.configure("test:unknown", {resultStatus: "unknown"});
  revisit.textarea.value = "Neuer Entwurf";
  revisit.textarea.change("input");
  assert.equal(revisit.submit("/dashboard/whatsapp/start-template").defaultPrevented, true);
  assert.equal(revisit.messageId.value, originalId);
});

test("a blocked test recipient prevents both diagnostic text and template submits", () => {
  const form = simpleFixture();
  form.controller.configure("test:blocked");
  form.form.dataset.dispatchBlocked = "true";
  assert.equal(form.submit().defaultPrevented, true);
  assert.equal(form.submit("/dashboard/whatsapp/start-template").defaultPrevented, true);
});

test("manual recovery requires its explicit confirmation dialog including dynamically inserted forms", () => {
  for (const accepted of [false, true]) {
    const callbacks = new Map();
    const prompts = [];
    const install = vm.runInNewContext(source + "\ninstallDispatchRecovery", {window: {confirm: text => {prompts.push(text); return accepted;}}});
    install({addEventListener: (event, callback) => callbacks.set(event, callback)});
    const event = {target: {matches: () => true}, submitter: {dataset: {resolutionConfirm: "Meta geprüft?"}},
      defaultPrevented: false, preventDefault() {this.defaultPrevented = true;}};
    callbacks.get("submit")(event);
    assert.equal(event.defaultPrevented, !accepted);
    assert.deepEqual(prompts, ["Meta geprüft?"]);
  }
});
