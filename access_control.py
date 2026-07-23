"""站点访问密码保护。

密码只从环境变量读取。登录成功后使用 HttpOnly Cookie 保存不可逆的认证令牌，
修改环境变量中的密码会自动让旧 Cookie 失效。
"""

from __future__ import annotations

import hashlib
import hmac
import html
from urllib.parse import quote

from fastapi import Request
from starlette.responses import HTMLResponse, RedirectResponse


COOKIE_NAME = "snack_studio_access"
COOKIE_MAX_AGE = 60 * 60 * 24 * 30
TOKEN_CONTEXT = b"snack-video-agent-access-v1"


class AccessControl:
    def __init__(self, password: str):
        self.password = password
        self.enabled = bool(password)
        self._token = (
            hmac.new(password.encode("utf-8"), TOKEN_CONTEXT, hashlib.sha256).hexdigest()
            if password
            else ""
        )

    @staticmethod
    def normalize_next_path(value: str | None) -> str:
        value = (value or "/").strip()
        if not value.startswith("/") or value.startswith("//"):
            return "/"
        return value

    def is_authenticated(self, request: Request) -> bool:
        if not self.enabled:
            return False
        cookie = request.cookies.get(COOKIE_NAME, "")
        return bool(cookie) and hmac.compare_digest(cookie, self._token)

    def login_page(
        self,
        *,
        next_path: str = "/",
        error: str = "",
        status_code: int = 200,
    ) -> HTMLResponse:
        safe_next = html.escape(self.normalize_next_path(next_path), quote=True)
        safe_error = html.escape(error)
        error_block = (
            f'<p class="error" role="alert">{safe_error}</p>' if safe_error else ""
        )
        body = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="robots" content="noindex,nofollow">
  <title>进入 Snack Studio</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; min-height: 100vh; display: grid; place-items: center;
      padding: 24px; color: #172018;
      font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
      background:
        radial-gradient(circle at 18% 18%, rgba(255,144,96,.24), transparent 34%),
        radial-gradient(circle at 82% 78%, rgba(105,180,142,.22), transparent 36%),
        #f6f2e9;
    }}
    .card {{
      width: min(420px, 100%); padding: 34px;
      border: 1px solid rgba(255,255,255,.78); border-radius: 28px;
      background: rgba(255,255,255,.68); backdrop-filter: blur(20px);
      box-shadow: 0 24px 70px rgba(42,51,43,.14);
    }}
    .eyebrow {{ margin: 0 0 12px; color: #f05a36; font-size: 12px; font-weight: 800; letter-spacing: .16em; }}
    h1 {{ margin: 0; font-size: 30px; line-height: 1.2; }}
    .desc {{ margin: 12px 0 24px; color: #657066; font-size: 14px; line-height: 1.7; }}
    label {{ display: block; margin-bottom: 8px; font-size: 13px; font-weight: 700; }}
    input {{
      width: 100%; height: 50px; padding: 0 16px;
      border: 1px solid #d9ddd5; border-radius: 14px; outline: none;
      background: rgba(255,255,255,.9); font-size: 16px;
    }}
    input:focus {{ border-color: #f05a36; box-shadow: 0 0 0 4px rgba(240,90,54,.12); }}
    button {{
      width: 100%; height: 50px; margin-top: 14px; border: 0; border-radius: 14px;
      color: white; background: #172018; font-size: 15px; font-weight: 800; cursor: pointer;
    }}
    button:hover {{ background: #2b382d; }}
    .error {{
      margin: 0 0 14px; padding: 10px 12px; border-radius: 10px;
      color: #a52b17; background: #fff0eb; font-size: 13px;
    }}
    .note {{ margin: 15px 0 0; color: #8a918a; font-size: 12px; text-align: center; }}
  </style>
</head>
<body>
  <main class="card">
    <p class="eyebrow">SNACK STUDIO</p>
    <h1>输入访问密码</h1>
    <p class="desc">该站点会调用付费视频模型，仅限授权访问。</p>
    {error_block}
    <form method="post" action="/auth/login">
      <input type="hidden" name="next" value="{safe_next}">
      <label for="password">访问密码</label>
      <input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
      <button type="submit">进入素材工厂</button>
    </form>
    <p class="note">密码不会写入网页或 GitHub</p>
  </main>
</body>
</html>"""
        return HTMLResponse(
            body,
            status_code=status_code,
            headers={"Cache-Control": "no-store"},
        )

    async def login(self, request: Request) -> HTMLResponse | RedirectResponse:
        form = await request.form()
        password = str(form.get("password", ""))
        next_path = self.normalize_next_path(str(form.get("next", "/")))

        if not self.enabled:
            return self.login_page(
                next_path=next_path,
                error="站点管理员尚未配置访问密码。",
                status_code=503,
            )
        if not hmac.compare_digest(password, self.password):
            return self.login_page(
                next_path=next_path,
                error="密码不正确，请重新输入。",
                status_code=401,
            )

        response = RedirectResponse(next_path, status_code=303)
        forwarded_proto = request.headers.get("x-forwarded-proto", request.url.scheme)
        response.set_cookie(
            COOKIE_NAME,
            self._token,
            max_age=COOKIE_MAX_AGE,
            httponly=True,
            secure=forwarded_proto.split(",")[0].strip().lower() == "https",
            samesite="strict",
            path="/",
        )
        return response

    @staticmethod
    def login_redirect(path: str) -> RedirectResponse:
        next_path = AccessControl.normalize_next_path(path)
        return RedirectResponse(f"/auth/login?next={quote(next_path, safe='/')}", status_code=303)

    @staticmethod
    def logout() -> RedirectResponse:
        response = RedirectResponse("/auth/login", status_code=303)
        response.delete_cookie(COOKIE_NAME, path="/")
        return response
