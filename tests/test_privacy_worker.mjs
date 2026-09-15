import assert from "node:assert/strict";
import { mock, test } from "node:test";
import worker from "../cloudflare/whatsapp-webhook-proxy/worker.js";

test("legal URLs lead to the configured app and discard unrelated query parameters", async () => {
  for (const method of ["GET", "HEAD"]) {
    for (const path of ["/impressum", "/datenschutz", "/datenschutz/rechte"]) {
      const request = new Request(`https://worker.example${path}/?workshop_id=a&token=private&next=https://other.example`, { method });
      const response = await worker.fetch(request, { UPSTREAM_URL: "https://app.example/meta/whatsapp?secret=private" });
      assert.equal(response.status, 302);
      assert.equal(response.headers.get("location"), `https://app.example${path}${path === "/datenschutz" ? "?workshop_id=a" : ""}`);
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(response.headers.get("referrer-policy"), "no-referrer");
      assert.equal(await response.text(), "");
    }
  }
});

test("Meta verification still requires the configured token", async () => {
  for (const token of ["test-verify-token", "wrong"]) {
    const response = await worker.fetch(new Request(`https://worker.example/?hub.mode=subscribe&hub.verify_token=${token}&hub.challenge=12345`),
      { WHATSAPP_VERIFY_TOKEN: "test-verify-token" });
    assert.equal(response.status, token === "test-verify-token" ? 200 : 403);
    if (response.status === 200) assert.equal(await response.text(), "12345");
  }
});

test("webhook forwarding preserves signed bytes and omits visitor credentials", async () => {
  const body = '{"entry":[{"test":"Grüße"}]}';
  const originalFetch = globalThis.fetch;
  globalThis.fetch = mock.fn(async (url, options) => {
    assert.equal(url, "https://app.example/meta/whatsapp");
    assert.equal(options.method, "POST");
    assert.equal(new TextDecoder().decode(options.body), body);
    assert.equal(options.headers.get("x-hub-signature-256"), "sha256=test-only");
    assert.equal(options.headers.get("cookie"), null);
    assert.equal(options.headers.get("authorization"), null);
    return new Response('{"ok":true}', { status: 200 });
  });
  try {
    const response = await worker.fetch(new Request("https://worker.example/", { method: "POST", body,
      headers: { "content-type": "application/json", "x-hub-signature-256": "sha256=test-only",
        cookie: "private=test", authorization: "Bearer test-only" } }), { UPSTREAM_URL: "https://app.example/meta/whatsapp" });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { ok: true });
    assert.equal(globalThis.fetch.mock.callCount(), 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});
