const DEFAULT_UPSTREAM_URL = "https://werkstattai-whatsapp.up.railway.app/meta/whatsapp";

function textResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/plain; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
    },
  });
}

function verifyWebhook(request, env) {
  const url = new URL(request.url);
  const mode = url.searchParams.get("hub.mode");
  const verifyToken = url.searchParams.get("hub.verify_token");
  const challenge = url.searchParams.get("hub.challenge");
  const expectedToken = String(env.WHATSAPP_VERIFY_TOKEN || "").trim();

  if (mode === "subscribe" && expectedToken && verifyToken === expectedToken && challenge) {
    return textResponse(challenge);
  }

  return textResponse("WhatsApp webhook verification failed", 403);
}

async function forwardWebhook(request, env) {
  const upstreamUrl = String(env.UPSTREAM_URL || DEFAULT_UPSTREAM_URL).trim();
  if (!upstreamUrl) {
    return jsonResponse({ ok: false, error: "UPSTREAM_URL is missing" }, 500);
  }

  const body = await request.arrayBuffer();
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  const signature = request.headers.get("x-hub-signature-256");

  if (contentType) {
    headers.set("content-type", contentType);
  }
  if (signature) {
    headers.set("x-hub-signature-256", signature);
  }

  const upstreamResponse = await fetch(upstreamUrl, {
    method: "POST",
    headers,
    body,
  });

  const responseHeaders = new Headers(upstreamResponse.headers);
  responseHeaders.set("cache-control", "no-store");

  return new Response(upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: responseHeaders,
  });
}

export default {
  async fetch(request, env) {
    if (request.method === "GET") {
      return verifyWebhook(request, env);
    }

    if (request.method === "POST") {
      return forwardWebhook(request, env);
    }

    return textResponse("Method not allowed", 405);
  },
};
