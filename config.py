"""WebUI Next 配置模块"""
from urllib.parse import quote

from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse
import nonebot

from .utils.security import verify_access_token

app = nonebot.get_app()

# CORS 配置
# 部署形态是同域单部署（页面由本进程伺服，浏览器请求同源，不经过 CORS），
# 开发环境 5173 与 8080 跨源，需要放行本机开发端口。
# allow_credentials 必须为 False：鉴权走 Authorization 头而不是 cookie，
# 开着它 + origins=["*"] 等于向任意网站开放带凭证跨源请求
origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,  # 无 cookie 会话，凭证标志关闭
    allow_methods=["*"],      # 允许所有 HTTP 方法
    allow_headers=["*"],      # 允许所有 HTTP 头（含 Authorization）
)

# ==================== WebUI 页面导航闸门 ====================
# dist 挂在 /next，纯前端的路由守卫拦不住"直接输 URL 加载页面"——
# 未登录时 index.html 照样下发。这里在伺服层拦截：浏览器页面导航
# （Accept 带 text/html）除登录页外，必须携带有效会话
# cookie（登录后由前端写入 zx_auth=<JWT>，内容与 localStorage 的
# token 同源，签名由 verify_access_token 校验），否则 302 到登录页。
# 只豁免登录页；/bot（模拟端）同样要求登录，页面内置的登录视图仅
# 作为会话中 token 过期的兜底。
# 静态资源与 API/WS 请求（Accept 不含 text/html 或非 /next 路径）
# 不拦：登录页自身的 JS/CSS 必须能加载，API/WS 有各自的鉴权
_NEXT_PAGE_EXEMPT = {"/next/login"}


@app.middleware("http")
async def webui_next_page_gate(request, call_next):
    path = request.url.path
    if path.startswith("/next") and "text/html" in request.headers.get("accept", ""):
        normalized = path.rstrip("/") or "/next"
        if normalized not in _NEXT_PAGE_EXEMPT:
            token = request.cookies.get("zx_auth", "")
            if not token or not verify_access_token(token):
                # gate=1 供前端守卫识别"被闸门弹回"：已登录但 cookie 缺失的
                # 老会话由此静默回原页面，不再当作"已登录访问登录页"处理；
                # redirect 带上原始路径（前端会校验同源路径防开放重定向）
                target = f"/next/login?gate=1&redirect={quote(path)}"
                return RedirectResponse(url=target, status_code=302)
    return await call_next(request)
