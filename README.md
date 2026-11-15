# Cue

Retrieve and copy captions from up to ten YouTube video URLs.

Hosted app: https://cue-orcin-zeta.vercel.app/

## Local development

```sh
uv venv
source .venv/bin/activate
uv pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000/.

## Vercel

The Vercel project `cue` is connected to this repository's `main` branch.
Vercel loads the Flask application in `app.py` and serves `public/static/`
assets from its CDN. Pushes to `main` deploy automatically.

YouTube currently blocks direct transcript requests from this Vercel deployment.
In Vercel's project settings, add `YOUTUBE_PROXY_URL` as a sensitive environment
variable for Production (and Preview if needed), then redeploy. Its value is the
authenticated HTTP/HTTPS proxy URL supplied by your proxy provider. Do not commit
credentials. A working rotating residential proxy may be necessary; configuring
a proxy does not guarantee YouTube will accept its requests.

Verify by submitting a public captioned YouTube video in the hosted app. An HTTP
200 response alone is insufficient: the API result must contain transcript `text`.
