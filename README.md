# Indeed MCP test server (step 1: search only)

## Deploy on Render
1. Put these 4 files in a private GitHub repo.
2. Render -> New -> Web Service -> pick the repo -> Runtime: Docker.
3. Environment variables:
   - MCP_SECRET = long random string (generate: python -c "import secrets; print(secrets.token_urlsafe(32))")
   - INDEED_HOST = ca.indeed.com (optional)
4. Health check path: /healthz
5. Your connector URL: https://<your-app>.onrender.com/<MCP_SECRET>/mcp
6. Claude -> Settings -> Connectors -> Add custom connector -> paste that URL.

## Test
Ask Claude: "Use search_jobs to find QA lead jobs in Calgary."
- blocked=True            -> Indeed is blocking Render's IP; this approach won't work from the cloud.
- blocked=False, count>0  -> step 1 passed, move to prepare_application.
- blocked=False, count=0  -> loaded but selectors need updating.

Note: the free Render tier spins down when idle; first call can take ~1 minute.
