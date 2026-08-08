const DEFAULT_UPSTREAM_URL = "https://werkstattai-whatsapp.up.railway.app/meta/whatsapp";

const PRIVACY_POLICY_HTML = `<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="index,follow">
  <title>Datenschutz - WerkstattAI</title>
  <style>
    :root{--bg:#f5f7f8;--surface:#fff;--text:#172126;--muted:#526168;--line:#d9e0e3;--accent:#087f73;--warm:#b45309}
    *{box-sizing:border-box}body{margin:0;min-height:100vh;color:var(--text);background:var(--bg);font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif;line-height:1.65}
    header{border-bottom:1px solid var(--line);background:var(--surface)}.inner,main,footer{width:min(860px,calc(100% - 40px));margin:0 auto}.inner{padding:28px 0 24px}
    .brand{color:var(--accent);font-size:14px;font-weight:800}h1{margin:8px 0 6px;font-size:clamp(30px,5vw,46px);line-height:1.12;letter-spacing:0}.lead{margin:0;color:var(--muted)}
    main{padding:34px 0 48px}section{padding:24px 0;border-bottom:1px solid var(--line)}section:first-child{padding-top:0}h2{margin:0 0 10px;font-size:21px;line-height:1.3;letter-spacing:0}
    p{margin:0 0 12px}p:last-child{margin-bottom:0}ul{margin:10px 0 0;padding-left:22px}li{margin:7px 0}a{color:var(--accent);font-weight:650}.notice{margin:0 0 28px;padding:14px 16px;border-left:4px solid var(--warm);background:#fff7ed;color:#6b3a0c}address{font-style:normal}footer{padding:22px 0 34px;color:var(--muted);font-size:13px}
    @media(max-width:600px){.inner,main,footer{width:min(100% - 28px,860px)}.inner{padding-top:22px}main{padding-top:26px}}
  </style>
</head>
<body>
  <header><div class="inner"><div class="brand">WerkstattAI</div><h1>Datenschutzinformation</h1><p class="lead">Informationen zur Verarbeitung personenbezogener Daten im WerkstattAI-Testbetrieb.</p></div></header>
  <main>
    <p class="notice">WerkstattAI befindet sich in einer technischen Testphase. Die Anwendung ist derzeit nicht für den regulären Einsatz mit echten Werkstattkunden freigegeben.</p>
    <section><h2>1. Verantwortlicher</h2><address>Mikolaj Olszewski<br>Kontakt: <a href="mailto:kontakt.werkstattai.de@outlook.com">kontakt.werkstattai.de@outlook.com</a></address></section>
    <section><h2>2. Zweck der Verarbeitung</h2><p>WerkstattAI erprobt die digitale Annahme und Bearbeitung von Werkstattanfragen. Nachrichten können erfasst, einem Vorgang zugeordnet und zur Vorbereitung einer Antwort verarbeitet werden. Während der Testphase dürfen nur ausdrücklich freigegebene Testdaten verwendet werden.</p></section>
    <section><h2>3. Verarbeitete Daten</h2><p>Je nach Nutzung können insbesondere folgende Daten verarbeitet werden:</p><ul><li>WhatsApp-Telefonnummer und gegebenenfalls der dort hinterlegte Profilname,</li><li>Inhalt ein- und ausgehender Nachrichten,</li><li>Angaben zu Fahrzeugen, Schäden, Terminen und Werkstattanfragen,</li><li>Zeitpunkte, Nachrichtenstatus und technische Kennungen,</li><li>technische Protokolldaten für Betrieb, Sicherheit und Fehleranalyse.</li></ul></section>
    <section><h2>4. Rechtsgrundlagen</h2><p>Im Testbetrieb erfolgt die Verarbeitung mit Einwilligung der teilnehmenden Testpersonen nach Art. 6 Abs. 1 Buchst. a DSGVO. Soweit eine Anfrage auf einen Vertrag oder vorvertragliche Maßnahmen gerichtet ist, kann Art. 6 Abs. 1 Buchst. b DSGVO einschlägig sein. Technisch notwendige Verarbeitungen können auf Art. 6 Abs. 1 Buchst. f DSGVO beruhen.</p></section>
    <section><h2>5. Eingesetzte Dienste und Empfänger</h2><p>Für den technischen Betrieb können Daten an Meta Platforms Ireland Limited, Cloudflare, Railway und, sofern die optionale KI-Unterstützung aktiviert ist, OpenAI Ireland Limited übermittelt werden.</p><p>Bei einzelnen Dienstleistern kann eine Verarbeitung außerhalb der EU oder des EWR stattfinden. In diesem Fall werden die jeweils erforderlichen datenschutzrechtlichen Übermittlungsmechanismen des Dienstleisters zugrunde gelegt.</p></section>
    <section><h2>6. Speicherdauer</h2><p>Personenbezogene Daten werden nur so lange gespeichert, wie sie für den jeweiligen Test, die Bearbeitung einer Anfrage, die technische Fehleranalyse oder gesetzliche Pflichten erforderlich sind. Nicht mehr benötigte Testdaten werden gelöscht oder anonymisiert.</p></section>
    <section><h2>7. Rechte betroffener Personen</h2><p>Betroffene Personen haben im Rahmen der gesetzlichen Voraussetzungen insbesondere Rechte auf Auskunft, Berichtigung, Löschung, Einschränkung der Verarbeitung, Datenübertragbarkeit und Widerspruch. Eine Einwilligung kann jederzeit mit Wirkung für die Zukunft widerrufen werden.</p><p>Zur Ausübung dieser Rechte genügt eine Nachricht an <a href="mailto:kontakt.werkstattai.de@outlook.com">kontakt.werkstattai.de@outlook.com</a>. Zusätzlich besteht ein Beschwerderecht bei einer zuständigen Datenschutzaufsichtsbehörde.</p></section>
    <section><h2>8. Automatisierte Entscheidungen</h2><p>WerkstattAI trifft keine Entscheidungen mit rechtlicher oder ähnlich erheblicher Wirkung ausschließlich automatisiert im Sinne von Art. 22 DSGVO.</p></section>
    <section><h2>9. Änderungen</h2><p>Diese Datenschutzinformation wird angepasst, wenn sich der Funktionsumfang, die eingesetzten Dienste oder die rechtlichen Anforderungen ändern.</p></section>
  </main>
  <footer>Stand: 8. August 2026</footer>
</body>
</html>`;

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

function htmlResponse(body, status = 200) {
  return new Response(body, {
    status,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "cache-control": "public, max-age=300",
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
    const url = new URL(request.url);

    if (request.method === "GET" && ["/datenschutz", "/datenschutz/"].includes(url.pathname)) {
      return htmlResponse(PRIVACY_POLICY_HTML);
    }

    if (request.method === "GET") {
      return verifyWebhook(request, env);
    }

    if (request.method === "POST") {
      return forwardWebhook(request, env);
    }

    return textResponse("Method not allowed", 405);
  },
};
