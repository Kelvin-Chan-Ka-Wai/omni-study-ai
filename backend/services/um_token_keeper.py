import re
from pathlib import Path
import httpx
from config import ROOT_ENV_PATH, settings
from database import STORAGE_DIR

PROFILE_DIR = STORAGE_DIR / "umpass_browser_profile"
PROFILE_DIR.mkdir(parents=True, exist_ok=True)


class UMTokenKeeper:
    """
    Smart UMPASS Token Keeper:
    1. Checks local macOS browsers (Chrome/Edge/Brave/Arc/Safari) for an active token cookie.
    2. Uses a persistent Chromium profile (storage/umpass_browser_profile) so 2FA / trusted-device
       cookies persist across sessions.
    3. Tries silent headless SSO first; if UMPASS asks for 2FA or multi-step input, automatically
       opens a visible Chromium window with credentials pre-filled so the user can approve once.
    """

    @staticmethod
    def persist_env_key(key: str, value: str) -> None:
        env_text = ROOT_ENV_PATH.read_text(encoding="utf-8") if ROOT_ENV_PATH.exists() else ""
        pattern = re.compile(rf"^{re.escape(key)}=.*$", flags=re.MULTILINE)
        if pattern.search(env_text):
            env_text = pattern.sub(f"{key}={value}", env_text)
        else:
            env_text = env_text.rstrip() + f"\n{key}={value}\n"
        ROOT_ENV_PATH.write_text(env_text, encoding="utf-8")

    @staticmethod
    async def is_um_campus_reachable() -> bool:
        try:
            async with httpx.AsyncClient(timeout=2.0, trust_env=False, verify=False) as client:
                resp = await client.get("https://chat.genai.um.edu.mo")
                return resp.status_code < 500
        except Exception:
            return False

    @staticmethod
    async def _verify_token_works(token: str) -> bool:
        if not token or not token.startswith("eyJ"):
            return False
        headers = {
            "Authorization": f"Bearer {token}",
            "Cookie": f"token={token}",
            "Accept": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=2.5, trust_env=False, verify=False) as client:
                r = await client.get(f"{settings.OPEN_WEBUI_BASE_URL}/models", headers=headers)
                return r.status_code == 200
        except Exception:
            return False

    @classmethod
    async def try_browser_cookie_sync(cls) -> str | None:
        try:
            import browser_cookie3
            for loader in (
                browser_cookie3.chrome,
                browser_cookie3.edge,
                browser_cookie3.brave,
                browser_cookie3.arc,
                browser_cookie3.safari,
            ):
                try:
                    cj = loader(domain_name="chat.genai.um.edu.mo")
                    for cookie in cj:
                        if cookie.name == "token" and cookie.value and cookie.value.startswith("eyJ"):
                            candidate = cookie.value.strip()
                            if await cls._verify_token_works(candidate):
                                settings.OPEN_WEBUI_API_KEY = candidate
                                cls.persist_env_key("OPEN_WEBUI_API_KEY", candidate)
                                return candidate
                except Exception:
                    continue
        except Exception:
            pass
        return None

    @classmethod
    async def _extract_token_from_context(cls, context, page) -> str | None:
        cookies = await context.cookies("https://chat.genai.um.edu.mo")
        for c in cookies:
            val = str(c.get("value", ""))
            if c.get("name") == "token" and val.startswith("eyJ"):
                return val
        if "chat.genai.um.edu.mo" in page.url:
            try:
                ls_token = await page.evaluate("() => localStorage.getItem('token')")
                if ls_token and str(ls_token).startswith("eyJ"):
                    return str(ls_token)
            except Exception:
                pass
        return None

    @classmethod
    async def _attempt_playwright_sso(cls, headless: bool) -> tuple[str | None, str]:
        username = (settings.UMPASS_USERNAME or "").strip()
        password = (settings.UMPASS_PASSWORD or "").strip()
        if not username or not password:
            return None, "UMPASS_USERNAME or UMPASS_PASSWORD missing in .env."

        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=headless,
                ignore_https_errors=True,
                args=["--disable-blink-features=AutomationControlled"],
            )
            page = context.pages[0] if context.pages else await context.new_page()

            try:
                await page.goto("https://chat.genai.um.edu.mo", wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1200)

                # Check if persistent profile is already logged in
                tok = await cls._extract_token_from_context(context, page)
                if tok and await cls._verify_token_works(tok):
                    await context.close()
                    return tok, "Refreshed token via saved UMPASS session!"

                # Click OAuth / UMPASS button on Open WebUI login screen if present
                if "chat.genai.um.edu.mo" in page.url:
                    for selector in [
                        "button:has-text('UMPASS')",
                        "button:has-text('OAuth')",
                        "button:has-text('Continue with')",
                        "button:has-text('Sign in')",
                        "a[href*='oauth']",
                        "button[type='submit']",
                    ]:
                        loc = page.locator(selector)
                        if await loc.count() > 0:
                            await loc.first.click()
                            await page.wait_for_timeout(1500)
                            break

                # Fill Username (supports both single-page ADFS and 2-step Entra/Azure SSO)
                for u_sel in [
                    "input#userNameInput",
                    "input[name='UserName']",
                    "input[name='loginfmt']",
                    "input[name='username']",
                    "input[type='email']",
                    "input[type='text']",
                ]:
                    loc = page.locator(u_sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.fill(username)
                        # If password box isn't visible yet (2-step login), click Next
                        pass_visible = await page.locator("input[type='password']").count() > 0
                        if not pass_visible:
                            await page.keyboard.press("Enter")
                            await page.wait_for_timeout(1200)
                        break

                # Fill Password
                for p_sel in [
                    "input#passwordInput",
                    "input[name='Password']",
                    "input[name='passwd']",
                    "input[name='password']",
                    "input[type='password']",
                ]:
                    loc = page.locator(p_sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.fill(password)
                        break

                # Submit form
                submitted = False
                for s_sel in [
                    "span#submitButton",
                    "input#submitButton",
                    "input[type='submit']",
                    "button[type='submit']",
                ]:
                    loc = page.locator(s_sel)
                    if await loc.count() > 0 and await loc.first.is_visible():
                        await loc.first.click()
                        submitted = True
                        break
                if not submitted:
                    await page.keyboard.press("Enter")

                # Wait for redirect back to chat.genai.um.edu.mo (8s if headless, 45s if visible for 2FA approval)
                max_polls = 16 if headless else 90
                for _ in range(max_polls):
                    await page.wait_for_timeout(500)
                    # Click "Yes" on "Stay signed in?" prompt if shown
                    stay_btn = page.locator("input#idSIButton9, button:has-text('Yes')")
                    if await stay_btn.count() > 0 and await stay_btn.first.is_visible():
                        try:
                            await stay_btn.first.click()
                        except Exception:
                            pass

                    tok = await cls._extract_token_from_context(context, page)
                    if tok and await cls._verify_token_works(tok):
                        await context.close()
                        return tok, "Logged into UMPASS & saved fresh 9-hour token!"

                final_url = page.url
                await context.close()
                return None, f"Stopped on URL: {final_url}"
            except Exception as e:
                await context.close()
                return None, f"{type(e).__name__}: {e}"

    @classmethod
    async def try_headless_umpass_login(cls) -> tuple[str | None, str]:
        if not await cls.is_um_campus_reachable():
            return None, "Not on UM Campus network (chat.genai.um.edu.mo unreachable)."

        # 1. Try silent background login first (8 seconds max)
        tok, msg = await cls._attempt_playwright_sso(headless=True)
        if tok:
            settings.OPEN_WEBUI_API_KEY = tok
            cls.persist_env_key("OPEN_WEBUI_API_KEY", tok)
            return tok, msg

        # 2. If headless stopped on 2FA or interactive prompt, open a visible window once so user can approve
        tok_vis, msg_vis = await cls._attempt_playwright_sso(headless=False)
        if tok_vis:
            settings.OPEN_WEBUI_API_KEY = tok_vis
            cls.persist_env_key("OPEN_WEBUI_API_KEY", tok_vis)
            return tok_vis, msg_vis

        return None, f"UMPASS login incomplete ({msg_vis}). Verify your UMPASS ID/Password in Settings (Cmd+,)."

    @classmethod
    async def auto_heal_token(cls) -> tuple[str | None, str]:
        cookie_tok = await cls.try_browser_cookie_sync()
        if cookie_tok:
            return cookie_tok, "Synced active UM token from local browser!"
        return await cls.try_headless_umpass_login()
