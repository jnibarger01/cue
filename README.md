# Cue

Cue is a private, single-user YouTube transcript workspace. The web application and login run on Vercel. A narrowly scoped worker on the owner's CachyOS workstation retrieves transcripts using the workstation's normal internet connection.

There is no registration flow and no public transcript endpoint.

## Request path

1. You sign in to Cue with the one configured username and password.
2. Vercel validates the signed session and CSRF token.
3. Vercel sends the requested YouTube URLs to the worker using a separate high-entropy bearer token.
4. The worker validates the token and accepts only YouTube transcript requests. It has no shell, filesystem, or general-purpose proxy endpoint.
5. The worker returns captions to Vercel, which returns them to the signed-in browser.

The worker binds to `127.0.0.1:8787`. Tailscale Funnel provides an HTTPS path to that one service; no router port forwarding is required. The Funnel URL is public by design, so the worker's bearer token is mandatory and must never be placed in browser code.

## 1. Configure the single login

Create a password hash locally. The password is entered through a hidden prompt and is never printed:

```sh
cd ~/projects/cue
uv run python scripts/hash_password.py
```

Copy the resulting hash into Vercel as a sensitive environment variable. Generate independent random secrets for the session and worker:

```sh
openssl rand -hex 32
openssl rand -hex 32
```

In Vercel, open the `cue` project, then Settings → Environment Variables. Add these for Production:

| Variable | Value |
|---|---|
| `CUE_USERNAME` | Your chosen username |
| `CUE_PASSWORD_HASH` | Output from `scripts/hash_password.py` |
| `CUE_SESSION_SECRET` | First random value |
| `CUE_WORKER_TOKEN` | Second random value |
| `CUE_WORKER_URL` | `https://cachyos-x8664.tailaa6d41.ts.net/cue-worker` |
| `CUE_COOKIE_SECURE` | `true` |

Do not put the plaintext password or either secret in Git, a browser variable, or chat. The password hash uses salted scrypt. Sessions are HttpOnly, Secure, SameSite=Lax, CSRF-protected, and expire after 12 hours.

If the machine's Funnel hostname changes, update `CUE_WORKER_URL`.

## 2. Install the workstation worker

On CachyOS, in the canonical checkout at `~/projects/cue`:

```sh
cd ~/projects/cue
uv venv
uv pip install -r requirements.txt
install -d -m 700 ~/.config/cue
$EDITOR ~/.config/cue/worker.env
chmod 600 ~/.config/cue/worker.env
```

Put the same `CUE_WORKER_TOKEN` value used in Vercel in `~/.config/cue/worker.env`:

```sh
CUE_WORKER_TOKEN=PASTE_THE_RANDOM_WORKER_SECRET_HERE
```

Install and start the user service:

```sh
install -Dm644 deploy/cue-worker.service ~/.config/systemd/user/cue-worker.service
systemctl --user daemon-reload
systemctl --user enable --now cue-worker.service
systemctl --user status cue-worker.service
```

If the worker must stay running after you log out and across reboots, enable user lingering:

```sh
sudo loginctl enable-linger "$USER"
```

The service runs one Gunicorn worker with bounded request concurrency, binds only to loopback, and uses systemd filesystem/process hardening.

## 3. Add the isolated Tailscale Funnel path

The current machine Funnel already has a root route used by another local service. Add Cue on a separate path; do not replace or reset the existing root route:

```sh
tailscale funnel --bg --set-path /cue-worker 8787
tailscale funnel status
```

Confirm the status still shows the existing `/` route to port 8010 and also shows `/cue-worker` to port 8787.

Check the local worker:

```sh
curl -i http://127.0.0.1:8787/healthz
```

Check the public worker path without a token. It must reject the request with HTTP 401 (or 404 if the Funnel path is not yet mapped to the worker):

```sh
curl -i -X POST https://cachyos-x8664.tailaa6d41.ts.net/cue-worker \
  -H 'Content-Type: application/json' \
  --data '{"urls":["https://youtu.be/abcdefghijk"]}'
```

Never test by putting the bearer token directly into shell history. Use the Vercel server-side request or a temporary protected environment variable if an authenticated diagnostic is needed.

## 4. Deploy and verify

After setting the Vercel variables and starting the worker, redeploy Cue. Then:

- Visit the hosted app and confirm it redirects to the login screen.
- Confirm a wrong password is rejected.
- Sign in and submit a public video that has captions.
- Confirm the result contains transcript text, not merely an HTTP 200 response.
- Sign out and confirm the transcript API returns HTTP 401 without a session.

If the workstation is offline, the application returns a controlled 503. It does not fall back to YouTube requests from Vercel. If YouTube also blocks the residential connection, an optional `YOUTUBE_PROXY_URL` can be set in the worker's local environment file.

## Security boundaries and limits

- Only one username/password is supported. There is no registration, password reset, or multi-user account system.
- The Vercel app never sends the login password to the worker.
- The worker token is separate from the browser session and is sent only from Vercel to the worker.
- The worker accepts only a bounded list of YouTube URLs, up to ten per request, with at most two concurrent batches.
- The login failure counter is process-local best-effort protection. For a stronger public perimeter, add a Vercel Firewall or Cloudflare rate-limit rule for `/login`.
- Tailscale Funnel makes only the configured worker path publicly reachable; it does not make the worker private. The bearer token is what authorizes worker requests.
- YouTube may still block a residential IP or restrict individual videos. Running locally improves the network path but does not guarantee every transcript is available.

## Tests

```sh
uv run --offline --with pytest --with 'Flask>=3.1,<4' --with 'requests>=2.32.4,<3' --with 'youtube-transcript-api==1.2.5' python -m pytest -q
```
