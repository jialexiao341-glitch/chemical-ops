"""API 响应的统一浏览器安全边界。"""
from starlette.datastructures import MutableHeaders


class SecurityHeadersMiddleware:
    def __init__(self, app, *, production: bool = False):
        self.app = app
        self.production = production

    async def __call__(self, scope, receive, send):
        async def send_response(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Content-Type-Options", "nosniff")
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "same-origin")
                headers.setdefault("Content-Security-Policy", "frame-ancestors 'none'")
                if self.production:
                    headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
            await send(message)
        await self.app(scope, receive, send_response)
