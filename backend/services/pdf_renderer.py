"""Print self-contained local HTML to an actual PDF; no third-party requests."""
from pathlib import Path
from playwright.async_api import async_playwright

ASSETS = Path(__file__).resolve().parent.parent / 'assets' / 'katex'


async def render_pdf(document):
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        try:
            page = await browser.new_page()
            async def local_assets(route):
                from urllib.parse import urlsplit
                url = urlsplit(route.request.url)
                if url.hostname == 'assets.omnistudy.local':
                    path = (ASSETS / url.path.lstrip('/')).resolve()
                    if path.is_relative_to(ASSETS.resolve()) and path.is_file():
                        return await route.fulfill(path=str(path))
                await route.abort()
            await page.route('**/*', local_assets)
            await page.set_content(document, wait_until='load')
            await page.wait_for_function('window.formulasReady === true', timeout=15000)
            await page.evaluate('document.fonts.ready')
            return await page.pdf(format='A4', print_background=True, margin={'top':'18mm','bottom':'18mm','left':'18mm','right':'18mm'})
        finally:
            await browser.close()
