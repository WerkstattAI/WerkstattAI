# WerkstattAI WhatsApp Webhook Proxy

Cloudflare Worker proxy for Meta WhatsApp webhooks.

## What It Does

- `GET` requests from Meta are verified directly by the Worker.
- `POST` webhook payloads are forwarded to Railway:
  `https://werkstattai-whatsapp.up.railway.app/meta/whatsapp`

Use this Worker URL as the Meta callback URL instead of the Railway URL.

The Worker also serves the public privacy policy at `/datenschutz`, avoiding
application-host rate limits when Meta validates the URL.

Set the same Worker URL in the app environment as `WHATSAPP_WEBHOOK_PUBLIC_URL`
so the dashboard shows the public callback URL.

## Deploy With Cloudflare Dashboard

1. Open Cloudflare Workers.
2. Create a new Worker.
3. Paste `worker.js`.
4. Add the upstream as an environment variable and the verify token as an
   encrypted secret. Generate your own long random verify token; never commit it.

```text
UPSTREAM_URL=https://werkstattai-whatsapp.up.railway.app/meta/whatsapp
```

With Wrangler, store the verify token separately:

```powershell
wrangler secret put WHATSAPP_VERIFY_TOKEN
```

5. Deploy.

6. In the WerkstattAI app/Railway environment, set:

```text
WHATSAPP_WEBHOOK_PUBLIC_URL=https://<your-worker-url>
```

## Deploy With Wrangler

```powershell
cd cloudflare/whatsapp-webhook-proxy
wrangler deploy
```

## Meta Callback Settings

Callback URL:

```text
https://<your-worker-url>/ 
```

Use the exact Worker URL without a trailing slash if Cloudflare shows it that way.

Verify token:

```text
<the same private verify token configured in Cloudflare and Railway>
```

For Graph API Explorer:

```json
{
  "object": "whatsapp_business_account",
  "callback_url": "https://<your-worker-url>",
  "verify_token": "<the same private verify token>",
  "fields": "messages"
}
```
