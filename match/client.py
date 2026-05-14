from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING, Any
from urllib.parse import urlencode

from astrbot.api import logger

from .models import MatchRecord, normalize_current_items, normalize_schedule

if TYPE_CHECKING:
    import httpx


SCHEDULE_API_BASE_URL = "https://schedule.scutbot.cn"
OFFICIAL_LIVE_JSON_BASE_URL = (
    "https://pro-robomasters-hz-n5i3.oss-cn-hangzhou.aliyuncs.com/live_json"
)
MAX_CACHE_ITEMS = 256


class MatchApiClient:
    def __init__(self, config: Any):
        self.config = config
        self._cache: dict[str, tuple[float, Any]] = {}
        self._client: httpx.AsyncClient | None = None
        self._httpx: Any | None = None

    async def close(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def matches(self) -> list[MatchRecord]:
        source = self.api_source()
        if source == "schedule":
            return normalize_schedule(await self.schedule_payload())
        if source == "official":
            return normalize_schedule(await self.official_schedule_payload())
        try:
            matches = normalize_schedule(await self.schedule_payload())
            if matches:
                return matches
            logger.warning("RM schedule API 返回空赛程，回退官方赛程接口")
        except Exception as exc:
            logger.warning(f"RM schedule API 不可用，回退官方赛程接口：{exc}")
        return normalize_schedule(await self.official_schedule_payload())

    async def current_matches(self) -> list[MatchRecord]:
        source = self.api_source()
        if source == "schedule":
            return [match for match in await self.matches() if match.is_live]
        if source == "official":
            return normalize_current_items(await self.official_current_payload())
        try:
            matches = [match for match in await self.matches() if match.is_live]
            if matches:
                return matches
        except Exception as exc:
            logger.warning(f"RM schedule 实时状态不可用，回退官方当前比赛接口：{exc}")
        return normalize_current_items(await self.official_current_payload())

    async def schedule_payload(self) -> Any:
        params = {}
        season = self.config._config_int("match_query_default_season", 0)
        if season > 0:
            params["season"] = str(season)
        return await self._get_json(self._schedule_url("/api/schedule", params), "schedule:schedule")

    async def official_schedule_payload(self) -> Any:
        return await self._get_json(
            self._official_live_json_url("schedule.json"),
            "official:schedule",
            ttl=5,
        )

    async def official_current_payload(self) -> Any:
        return await self._get_json(
            self._official_live_json_url("current_and_next_matches.json"),
            "official:current",
            ttl=5,
        )

    async def mp_match(self, match_id: str) -> dict[str, Any] | None:
        if not self.supports_schedule_extras():
            return None
        if not match_id:
            return None
        try:
            payload = await self._get_json(
                self._schedule_url("/api/mp/match", {"match_ids": match_id}),
                f"schedule:mp:{match_id}",
                ttl=30,
            )
        except Exception as exc:
            logger.warning(f"RM 小程序投票接口失败：{exc}")
            return None
        items = payload.get("list") if isinstance(payload, dict) else None
        return items[0] if isinstance(items, list) and items else None

    async def match_replay(self, match: MatchRecord) -> dict[str, Any] | None:
        if not self.supports_schedule_extras():
            return None
        if match.match_id:
            replay = await self._match_id_replay(match.match_id)
            if replay:
                return replay
        return await self._match_order_replay(match)

    async def history(self, primary: str, secondary: str) -> list[dict[str, Any]]:
        if not self.supports_schedule_extras():
            return []
        payload = await self._get_json(
            self._schedule_url(
                "/api/history_match",
                {
                    "primary_college_name": primary,
                    "secondary_college_name": secondary,
                },
            ),
            f"schedule:history:{primary}:{secondary}",
            ttl=300,
        )
        hits = payload.get("hits") if isinstance(payload, dict) else []
        return hits if isinstance(hits, list) else []

    async def _match_id_replay(self, match_id: str) -> dict[str, Any] | None:
        try:
            payload = await self._get_json(
                self._schedule_url("/api/match_id_to_video", {"match_id": match_id}),
                f"schedule:replay:id:{match_id}",
                ttl=300,
            )
        except Exception:
            return None
        return payload if isinstance(payload, dict) and payload.get("bvid") else None

    async def _match_order_replay(self, match: MatchRecord) -> dict[str, Any] | None:
        if not match.zone_name or not match.order_number:
            return None
        params: dict[str, str] = {
            "zone": match.zone_name,
            "order_number": str(match.order_number),
        }
        season = self.config._config_int("match_query_default_season", 0)
        if season > 0:
            params["season"] = str(season)
        try:
            cache_key = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            payload = await self._get_json(
                self._schedule_url("/api/match_order_to_video", params),
                f"schedule:replay:order:{cache_key}",
                ttl=300,
            )
        except Exception:
            return None
        return payload if isinstance(payload, dict) and payload.get("bvid") else None

    async def _get_json(self, url: str, key: str, ttl: int | None = None) -> Any:
        ttl = self.cache_seconds() if ttl is None else ttl
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and cached[0] > now:
            return cached[1]

        response = await self.http_client().get(url)
        response.raise_for_status()
        payload = response.json()
        self.remember_cache(key, now + max(1, ttl), payload, now)
        return payload

    def http_client(self) -> httpx.AsyncClient:
        if self._httpx is None:
            try:
                import httpx
            except ImportError as exc:
                raise RuntimeError(f"缺少 httpx：{exc}") from exc
            self._httpx = httpx
        if self._client is None:
            self._client = self._httpx.AsyncClient(timeout=15, follow_redirects=True)
        return self._client

    def remember_cache(self, key: str, expires_at: float, payload: Any, now: float) -> None:
        for cached_key, (expires, _) in list(self._cache.items()):
            if expires <= now:
                self._cache.pop(cached_key)
        while len(self._cache) >= MAX_CACHE_ITEMS:
            self._cache.pop(next(iter(self._cache)))
        self._cache[key] = (expires_at, payload)

    def _schedule_url(self, path: str, params: dict[str, str] | None = None) -> str:
        base = self.config._config_str("schedule_api_base_url", SCHEDULE_API_BASE_URL).rstrip("/")
        url = f"{base}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        return url

    def _official_live_json_url(self, name: str) -> str:
        base = self.config._config_str(
            "official_live_json_base_url",
            OFFICIAL_LIVE_JSON_BASE_URL,
        ).rstrip("/")
        return f"{base}/{name}"

    def api_source(self) -> str:
        source = self.config._config_str("match_api_source", "auto").strip().lower()
        return {
            "官方": "official",
            "官方 live_json": "official",
            "官方live_json": "official",
            "live_json": "official",
        }.get(source, source)

    def is_official_source(self) -> bool:
        return self.api_source() == "official"

    def supports_schedule_extras(self) -> bool:
        return not self.is_official_source()

    def cache_seconds(self) -> int:
        return max(1, self.config._config_int("match_query_cache_seconds", 15))
