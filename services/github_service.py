import asyncio
from datetime import datetime, timedelta

import httpx


class GitHubService:
    _cache = []
    _last_fetch = None
    _lock = asyncio.Lock()
    _refreshing = False

    CACHE_TTL = timedelta(minutes=20)

    API_URLS = [
        "https://api.github.com/repos/zhenxun-org/zhenxun_bot/commits?sha=main&per_page=30",
        "https://api.kkgithub.com/repos/zhenxun-org/zhenxun_bot/commits?sha=main&per_page=30",
    ]

    HEADERS = {
        "User-Agent": "Mozilla/5.0 ZhenxunBot/1.0",
        "Accept": "application/vnd.github+json",
    }

    @classmethod
    async def get_commits(cls):
        now = datetime.utcnow()

        # 缓存未过期
        if (
            cls._cache
            and cls._last_fetch
            and (now - cls._last_fetch < cls.CACHE_TTL)
        ):
            return cls._cache

        # 缓存过期，先返回旧缓存，再后台刷新
        if cls._cache:
            if not cls._refreshing:
                asyncio.create_task(cls._safe_refresh())
            return cls._cache

        # 首次加载必须等一次
        async with cls._lock:
            if cls._cache:
                return cls._cache

            await cls._safe_fetch()
            return cls._cache

    @classmethod
    async def _safe_refresh(cls):
        if cls._refreshing:
            return

        cls._refreshing = True
        try:
            await cls._safe_fetch()
        finally:
            cls._refreshing = False

    @classmethod
    async def _safe_fetch(cls):
        try:
            await cls._fetch()
        except Exception as e:
            # 失败不清缓存
            print("刷新 commits 失败:", e)

    @classmethod
    async def _fetch(cls):
        timeout = httpx.Timeout(10.0)

        async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
        ) as client:

            data = None

            for idx, url in enumerate(cls.API_URLS):
                try:
                    resp = await client.get(
                        url,
                        headers=cls.HEADERS,
                    )

                    # GitHub 403 -> fallback
                    if resp.status_code == 403 and idx == 0:
                        print("GitHub 403，切换 kkgithub...")
                        continue

                    resp.raise_for_status()

                    data = resp.json()
                    break

                except httpx.TimeoutException:
                    print(f"请求超时: {url}")

                except httpx.HTTPStatusError as e:
                    print(
                        f"HTTP {e.response.status_code}: "
                        f"{e.response.text[:150]}"
                    )

                except Exception as e:
                    print(f"请求异常 {url}: {e}")

            if not data:
                return

        result = []

        for c in data:
            try:
                commit = c.get("commit") or {}
                author = commit.get("author") or {}

                result.append({
                    "sha": (c.get("sha") or "")[:7],
                    "author": author.get("name"),
                    "avatar_url": (c.get("author") or {}).get("avatar_url"),
                    "date": author.get("date"),
                    "message": (
                            commit.get("message") or ""
                    ).splitlines()[0],
                })

            except Exception as e:
                print("commit parse error:", e)

        if result:
            cls._cache = result
            cls._last_fetch = datetime.utcnow()