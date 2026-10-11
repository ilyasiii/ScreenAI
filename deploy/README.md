# Deploying ScreenAI

The site has two halves, hosted separately:

| Part | Where | Address |
| :--- | :--- | :--- |
| Frontend (React) | GitHub Pages | `https://screenai.tech` |
| Backend (FastAPI) | Any Linux server with Docker | `https://api.screenai.tech` |

GitHub Pages only serves static files, so it cannot run the backend. The
workflow in `.github/workflows/deploy.yml` builds both: it publishes the site to
Pages and the backend as a Docker image on `ghcr.io`, then deploys that image to
your server once you have one.

## 1. Frontend on GitHub Pages

1. **Repo -> Settings -> Pages**: set *Source* to **GitHub Actions**. Under
   *Custom domain* enter `screenai.tech`, save, and tick **Enforce HTTPS** once
   the certificate is issued.
2. **Repo -> Settings -> Secrets and variables -> Actions -> Variables**, add:

   | Variable | Value |
   | :--- | :--- |
   | `VITE_API_URL` | `https://api.screenai.tech` |
   | `VITE_SUPABASE_URL` | `https://<project>.supabase.co` |
   | `VITE_SUPABASE_ANON_KEY` | the **anon** key (Supabase -> Project Settings -> API) |

   These are compiled into the public bundle, so they are variables, not
   secrets. The build refuses to run if the key is a `service_role` key.
3. **DNS for `screenai.tech`** at your registrar:

   | Type | Name | Value |
   | :--- | :--- | :--- |
   | `A` | `@` | `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` |
   | `AAAA` | `@` | `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, `2606:50c0:8003::153` |
   | `CNAME` | `www` | `ilyasiii.github.io` |

4. **Verify the domain** (your GitHub profile -> Settings -> Pages -> *Add a
   domain*). This stops anyone else's repository from claiming
   `screenai.tech` if your Pages site is ever unpublished.
5. Push to `main`. The *Deploy* workflow builds and publishes the site.

## 2. Supabase

- **Authentication -> URL Configuration**: *Site URL* `https://screenai.tech`;
  add `https://screenai.tech/**` to *Redirect URLs* (keep
  `http://localhost:5173/**` for development). Sign-up confirmation, Google
  sign-in and password reset all redirect here.
- **Authentication -> Providers -> Email**: set the minimum password length to
  8 to match the app, and keep *Confirm email* on.
- **Row Level Security** must be on for `analysis_history` and
  `usage_tracking`. The anon key is public; RLS is what protects the data. Run
  the SQL in the main README if you have not.

## 3. Backend on a server

Any small Linux VM works (1 vCPU / 1 GB is plenty), x86-64 or ARM: the image
is published for both.

1. Point DNS at it: `A` record `api` -> the server's IP.
2. Install Docker, then copy this folder to the server:

   ```bash
   scp -r deploy/ user@server:~/screenai
   ```

3. On the server, create `~/screenai/.env` from `backend/.env.example`. At
   minimum:

   ```env
   ENVIRONMENT=production
   SUPABASE_URL=https://<project>.supabase.co
   CORS_ORIGINS=https://screenai.tech,https://www.screenai.tech
   ```

   Leave the API keys blank so each user brings their own.

4. The image on `ghcr.io` is private by default. Either make it public
   (GitHub -> your profile -> Packages -> `screenai-backend` -> Package
   settings), or log the server in once with a token that has
   `read:packages`:

   ```bash
   echo <token> | docker login ghcr.io -u ilyasiii --password-stdin
   ```

5. Start it: `cd ~/screenai && docker compose up -d`. Caddy fetches the HTTPS
   certificate on first start. Check `https://api.screenai.tech/health`.

### Automatic backend deploys

To have every push to `main` update the server, add to the repo's Actions
settings:

| Kind | Name | Value |
| :--- | :--- | :--- |
| Variable | `DEPLOY_HOST` | server IP or hostname |
| Variable | `DEPLOY_USER` | SSH user (must be able to run `docker`) |
| Variable | `DEPLOY_HOST_FINGERPRINT` | the server's SSH host key fingerprint (below) |
| Secret | `DEPLOY_SSH_KEY` | private key for that user, ideally a key used only for this |

Get the fingerprint from a machine you trust, and check it matches what the
server shows locally (`ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`):

```bash
ssh-keyscan -t ed25519 <server> 2>/dev/null | ssh-keygen -lf - | awk '{print $2}'
```

Until `DEPLOY_HOST` is set, that job is skipped and everything else still runs.

The job pulls the new image and restarts it; it does not copy files. After
changing `deploy/docker-compose.yml` or `deploy/Caddyfile`, copy them to the
server again (`scp deploy/docker-compose.yml deploy/Caddyfile user@server:~/screenai/`)
and run `docker compose up -d` there.

## Using a managed host instead

The backend image runs anywhere that runs containers (Render, Railway, Fly.io,
Cloud Run). Point it at `backend/Dockerfile`, set the same environment variables
as step 3, give it the `api.screenai.tech` domain, and run **one** instance:
sessions and rate limits are held in memory.
