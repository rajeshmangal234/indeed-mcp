"""
Indeed MCP test server (step 1: search only, no login, no apply).
Goal: find out whether Indeed serves pages to a headless browser on Render.
"""
import os
import re
from urllib.parse import quote_plus

from mcp.server.fastmcp import FastMCP
from playwright.async_api import async_playwright

SECRET = os.environ["MCP_SECRET"]          # long random string, set in Render
INDEED_HOST = os.environ.get("INDEED_HOST", "ca.indeed.com")
PORT = int(os.environ.get("PORT", "10000"))

mcp = FastMCP("indeed-test", stateless_http=True, host="0.0.0.0", port=PORT)

BLOCK_MARKERS = ["captcha", "verify you are human", "unusual traffic",
                 "access denied", "blocked", "cf-challenge", "just a moment"]


async def _fetch(url: str) -> tuple[int, str, str]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = await browser.new_context(
            locale="en-CA",
            viewport={"width": 1366, "height": 800},
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        )
        page = await ctx.new_page()
        resp = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(2500)
        status = resp.status if resp else 0
        title = await page.title()
        html = await page.content()
        await browser.close()
        return status, title, html


def _blocked(status: int, title: str, html: str) -> bool:
    text = (title + " " + html[:5000]).lower()
    return status in (403, 429) or any(m in text for m in BLOCK_MARKERS)


@mcp.tool()
async def search_jobs(query: str, location: str = "Calgary, AB", limit: int = 10) -> dict:
    """Search Indeed for jobs. Returns title, company, location and link.
    If Indeed blocks the request, returns blocked=True with the HTTP status and page title."""
    limit = max(1, min(limit, 15))
    url = f"https://{INDEED_HOST}/jobs?q={quote_plus(query)}&l={quote_plus(location)}"
    status, title, html = await _fetch(url)

    if _blocked(status, title, html):
        return {"blocked": True, "http_status": status, "page_title": title, "url": url}

    # Selectors are best-effort; Indeed changes them often.
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()
        await page.set_content(html)
        cards = await page.query_selector_all("div.job_seen_beacon")
        jobs = []
        for c in cards[:limit]:
            t = await c.query_selector("h2.jobTitle span")
            co = await c.query_selector('[data-testid="company-name"]')
            lo = await c.query_selector('[data-testid="text-location"]')
            a = await c.query_selector("a.jcs-JobTitle")
            href = await a.get_attribute("href") if a else None
            jobs.append({
                "title": (await t.inner_text()).strip() if t else None,
                "company": (await co.inner_text()).strip() if co else None,
                "location": (await lo.inner_text()).strip() if lo else None,
                "link": f"https://{INDEED_HOST}{href}" if href else None,
            })
        await browser.close()

    return {"blocked": False, "http_status": status, "count": len(jobs), "jobs": jobs,
            "note": "count=0 with blocked=False usually means selectors need updating"}


@mcp.tool()
async def get_job_details(url: str) -> dict:
    """Open an Indeed job link and return its title and description text."""
    if not re.match(rf"^https://{re.escape(INDEED_HOST)}/", url):
        return {"error": f"URL must start with https://{INDEED_HOST}/"}
    status, title, html = await _fetch(url)
    if _blocked(status, title, html):
        return {"blocked": True, "http_status": status, "page_title": title}
    m = re.search(r'id="jobDescriptionText"[^>]*>(.*?)</div>\s*</div>', html, re.S)
    text = re.sub(r"<[^>]+>", " ", m.group(1)) if m else ""
    return {"blocked": False, "title": title,
            "description": re.sub(r"\s+", " ", text).strip()[:6000]}


class SecretPath:
    """ASGI wrapper: the MCP endpoint only exists at /<MCP_SECRET>/mcp."""
    def __init__(self, app, secret):
        self.app, self.prefix = app, f"/{secret}"

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope["path"]
            if path == "/healthz":
                await send({"type": "http.response.start", "status": 200,
                            "headers": [(b"content-type", b"text/plain")]})
                await send({"type": "http.response.body", "body": b"ok"})
                return
            if not path.startswith(self.prefix + "/"):
                await send({"type": "http.response.start", "status": 404, "headers": []})
                await send({"type": "http.response.body", "body": b""})
                return
            scope = dict(scope, path=path[len(self.prefix):])
        await self.app(scope, receive, send)


app = SecretPath(mcp.streamable_http_app(), SECRET)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
