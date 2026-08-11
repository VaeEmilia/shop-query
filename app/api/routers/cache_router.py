"""
缓存统计接口路由

提供 /api/cache/stats 接口，用于查询 SQL 缓存的命中率、命中次数和缓存条目数。
"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import get_sql_cache_service
from app.services.sql_cache_service import SQLCacheService

cache_router = APIRouter()


@cache_router.get("/api/cache/stats")
async def cache_stats(
    sql_cache_service: Annotated[SQLCacheService, Depends(get_sql_cache_service)],
):
    """返回 SQL 缓存命中率统计"""
    stats = await sql_cache_service.get_stats()
    return {
        "code": 0,
        "message": "success",
        "data": stats,
    }


@cache_router.post("/api/cache/stats/reset")
async def reset_cache_stats(
    sql_cache_service: Annotated[SQLCacheService, Depends(get_sql_cache_service)],
):
    """重置缓存命中率统计计数器"""
    await sql_cache_service.reset_stats()
    return {
        "code": 0,
        "message": "统计计数器已重置",
    }
