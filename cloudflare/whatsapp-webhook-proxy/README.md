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
4. Add environment variables:

```text
WHATSAPP_VERIFY_TOKEN=werkstattai-whatsapp-verify-2026
UPSTREAM_URL=https://werkstattai-whatsapp.up.railway.app/meta/whatsapp
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
werkstattai-whatsapp-verify-2026
```

For Graph API Explorer:

```json
{
  "object": "whatsapp_business_account",
  "callback_url": "https://<your-worker-url>",
  "verify_token": "werkstattai-whatsapp-verify-2026",
  "fields": "messages"
}
```
