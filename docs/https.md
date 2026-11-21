# HTTPS and phone install

This guide tells you how to give the server an HTTPS address and how to install the app on a phone.

## HTTPS

You need HTTPS for:

- push notifications (browsers allow them only on HTTPS),
- Claude connectors (Claude connects only to HTTPS servers),
- install on a phone as an app.

Two ways:

**Tailscale Funnel** gives you a public HTTPS address with no domain and no open port:

```bash
tailscale funnel --bg 8000      # https://<machine>.<tailnet>.ts.net -> 127.0.0.1:8000
```

Funnel must be on for your tailnet. The first `tailscale funnel` run prints a link to turn it on. Put the
`https://<machine>.<tailnet>.ts.net` address in `BASE_URL` and restart: `docker compose up -d`.

**Cloudflare Tunnel** gives your own domain (at Cloudflare) a public HTTPS address with no open port. In the
Cloudflare dashboard go to **Zero Trust > Networks > Tunnels**, make a tunnel, and add a public hostname with
the service `http://app:8000`. Put the tunnel token and the profile in `.env`, then start:

```bash
# .env
COMPOSE_PROFILES=tunnel
CLOUDFLARE_TUNNEL_TOKEN=<the token>
BASE_URL=https://<your hostname>
```

```bash
docker compose up -d
```

Set `OPERATOR_EMAILS` (or `ALLOWED_EMAILS`) first: the app is public when the tunnel runs. See
[A server for more than one family](sign-in.md#a-server-for-more-than-one-family-invite-only). Also set
`BEHIND_CLOUDFLARE=true`, so the rate limits see the address of each visitor.

Cloudflare stops a request that sends no data for 125 seconds. The app allows for this: the sleep plan and the
support report run as a job that the page asks about, the chat sends a heartbeat, and other requests that wait
for the model get "The assistant is busy" after 60 seconds.

**A reverse proxy** (Caddy, nginx, Traefik) with your own domain also works. Send all paths to port 8000. Do not
buffer responses: the assistant streams its answers (Server-Sent Events). Set `BASE_URL` to the public address.

## Install on a phone

1. Open your `BASE_URL` in the phone browser and sign in.
2. iPhone (Safari): **Share > Add to Home Screen**. Android (Chrome): **menu > Install app** (or **Add to Home
   screen**).
3. Open Frecklebubby from the Home Screen. Go to **Settings > Notifications** and select
   **Turn on notifications**. On iPhone, push works only in the app that you added to the Home Screen.

> Push on a real phone is not yet tested. The tests prove the reminder and the in-app notification, and the
> server's push sending code. See [Development](development.md#development).
