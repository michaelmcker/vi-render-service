# Cloudflare Tunnel + Cloudflare Access — setup runbook

This is what the operator does once during droplet provisioning. After
this, the web UI is reachable at `https://hermes.<your-zone>` ONLY for
the two emails listed in the Access policy. Nothing else on the internet
can hit the droplet's web UI.

## Prerequisites

- A Cloudflare account on the **Free** plan (everything below works on Free).
- A domain in Cloudflare DNS — VI's existing domain works. If VI doesn't
  use Cloudflare for DNS yet, change the nameservers to Cloudflare first
  (one-time, ~5 min, free).
- The droplet provisioned per `setup/install_droplet.sh` (Phase 7 — adds
  a `cloudflared` user and the systemd unit at `setup/cloudflared.service`).
- SSH access to the droplet.

## Step 1 — Install cloudflared on the droplet

```bash
curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i cloudflared.deb
cloudflared --version
```

## Step 2 — Authenticate cloudflared

```bash
cloudflared tunnel login
```

Cloudflare prints a URL. Open it in any browser, sign in to your
Cloudflare account, pick the zone (your domain), authorize. cloudflared
writes a cert to `~/.cloudflared/cert.pem`.

## Step 3 — Create the tunnel

```bash
cloudflared tunnel create hermes
```

Cloudflare assigns the tunnel a UUID (e.g.
`abcd1234-5678-9012-...`) and writes credentials to
`~/.cloudflared/<UUID>.json`.

## Step 4 — Wire DNS

```bash
cloudflared tunnel route dns hermes hermes.<your-zone>
```

Replace `<your-zone>` with VI's domain (e.g. `hermes.verticalimpression.com`).
This creates a CNAME pointing at the tunnel.

## Step 5 — Drop the config

```bash
sudo mkdir -p /etc/cloudflared
sudo cp /opt/hermes/setup/cloudflared.config.example.yml /etc/cloudflared/config.yml
sudo cp ~/.cloudflared/<UUID>.json /etc/cloudflared/
sudo nano /etc/cloudflared/config.yml
# replace REPLACE_WITH_TUNNEL_ID and REPLACE_WITH_YOUR_CF_ZONE
sudo useradd -r -s /usr/sbin/nologin cloudflared
sudo chown -R cloudflared:cloudflared /etc/cloudflared
sudo chmod 600 /etc/cloudflared/<UUID>.json

sudo cp /opt/hermes/setup/cloudflared.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cloudflared
sudo systemctl status cloudflared
```

## Step 6 — Cloudflare Access policy (the email allowlist)

This is the security gate that refuses everyone who isn't Nikki or the
operator at the EDGE — before any traffic reaches the droplet.

In the Cloudflare dashboard:

1. Navigate to **Zero Trust → Access → Applications**.
2. **Add an application → Self-hosted**.
3. Application name: `Hermes`.
4. Application domain: `hermes.<your-zone>`.
5. Session duration: `24 hours` (or shorter).
6. Click **Next** → **Add a policy**.
7. Policy name: `Allowed users`. Action: **Allow**.
8. Include rule: **Emails** → list `nikki@verticalimpression.com` and
   `<operator>@verticalimpression.com`. Anyone else is rejected at the edge.
9. Save. Save again. Done.

Cloudflare Access now requires a one-time-password or Google login (using
the email itself) before forwarding any request to cloudflared.

### Health-probe carve-out (optional but recommended)

cloudflared periodically hits `/healthz` to confirm the tunnel is alive.
The Hermes `/healthz` endpoint is intentionally unauthenticated, but the
Cloudflare Access policy in front of it normally requires a sign-in — so
the probe would fail.

In the Access application settings, under **Authentication**:

- Service tokens → leave empty.
- Bypass policy → for the path `/healthz` only.

(Or simpler: ignore the probe failures; cloudflared treats Access-block
responses as healthy enough.)

## Step 7 — Verify

From your laptop browser:

```
https://hermes.<your-zone>
```

You'll get the Cloudflare Access login screen. Sign in with the Google
email listed in the policy. After auth, the Hermes status dashboard
should load — every connection in green.

If you see a 403 or "not authorized" page from Hermes itself (not
Cloudflare), check `HERMES_WEB_ALLOWED_EMAILS` in `/opt/hermes/.env` —
both Nikki's and the operator's emails must be present there too.

## Step 8 — Tell Nikki

Send her the URL:
```
https://hermes.<your-zone>
```

She'll be prompted to sign in with her Google account on her phone the
first time. Cloudflare remembers the session for 24 hours. If she ever
needs to re-OAuth Google for Hermes itself (rare; refresh tokens last
for years), she'll tap a link from Telegram, sign in once with Google
through Cloudflare Access, and once again on Google's consent screen.

## What this gives us

- **No public ports on the droplet** — only SSH (key-only, root disabled).
- **No traffic reaches Hermes** without a verified email in the allowlist.
- **Defense in depth**: Hermes's `app/web/auth.py` re-validates the
  `Cf-Access-Authenticated-User-Email` header against
  `HERMES_WEB_ALLOWED_EMAILS`. If you ever misconfigure CF Access,
  Hermes still refuses unauthorized emails.
- **Free** — Cloudflare's free plan includes Tunnel + 50 Access seats.
