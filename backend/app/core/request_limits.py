"""在解析请求之前检查完整体积；大文件落临时文件，内存缓冲有界。"""
from tempfile import SpooledTemporaryFile

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, json_limit_bytes: int = 1024 * 1024,
                 multipart_limit_bytes: int = 51 * 1024 * 1024) -> None:
        self.app = app
        self.json_limit_bytes = json_limit_bytes
        self.multipart_limit_bytes = multipart_limit_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope['type'] != 'http' or scope.get('method') not in {'POST', 'PUT', 'PATCH', 'DELETE'}:
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get('headers', []))
        limit = (self.multipart_limit_bytes if headers.get(b'content-type', b'').lower().startswith(b'multipart/')
                 else self.json_limit_bytes)
        try:
            declared = int(headers.get(b'content-length', b'0'))
            if declared < 0:
                raise ValueError
        except ValueError:
            await JSONResponse({'detail': '请求长度无效'}, status_code=400)(scope, receive, send)
            return
        if declared > limit:
            await JSONResponse({'detail': '请求体超过允许大小'}, status_code=413)(scope, receive, send)
            return
        # 不相信 Content-Length；chunked 或虚报长度也按实际接收字节计数。
        with SpooledTemporaryFile(max_size=min(limit, 1024 * 1024)) as body:
            size = 0
            while True:
                message = await receive()
                if message['type'] == 'http.disconnect':
                    return
                chunk = message.get('body', b'')
                size += len(chunk)
                if size > limit:
                    await JSONResponse({'detail': '请求体超过允许大小'}, status_code=413)(scope, receive, send)
                    return
                body.write(chunk)
                if not message.get('more_body', False):
                    break
            body.seek(0)
            remaining = size

            async def replay():
                nonlocal remaining
                if remaining == 0:
                    # 空请求仍需先交付一次 http.request，之后交回真实接收器。
                    if body.tell() == 0:
                        body.seek(1)
                        return {'type': 'http.request', 'body': b'', 'more_body': False}
                    return await receive()
                chunk = body.read(min(65536, remaining))
                remaining -= len(chunk)
                return {'type': 'http.request', 'body': chunk, 'more_body': remaining > 0}

            await self.app(scope, replay, send)
