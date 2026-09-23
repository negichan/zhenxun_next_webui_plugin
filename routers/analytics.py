"""数据分析路由"""
from datetime import datetime

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..dependencies import AuthenticatedUser
from ..exceptions import APIException
from ..models.analytics import (
    AnalyticsOverview,
    DetailedStatisticsTimeRange,
    FavorabilityRank,
    GoldRank,
    MessageHeatmap,
    TrendData,
)
from ..responses import APIResponse, success_response
from ..services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["数据分析"])


@router.get(
    "/overview",
    response_model=APIResponse[AnalyticsOverview],
    response_class=JSONResponse,
    summary="获取区间概览 KPI",
)
async def get_overview(
    user: AuthenticatedUser,
    start_time: datetime = Query(..., description="起始时间 (ISO 格式)"),
    end_time: datetime = Query(..., description="结束时间 (ISO 格式)"),
    bot_id: str | None = Query(None, description="Bot ID"),
) -> APIResponse[AnalyticsOverview]:
    """获取区间概览 KPI

    返回所选时间范围内的消息/调用/日均/峰值/活跃数，以及上一等长周期对比值。

    Args:
        start_time: 起始时间 (ISO 格式)
        end_time: 结束时间 (ISO 格式)
        bot_id: Bot ID，可选

    Returns:
        APIResponse[AnalyticsOverview]: 区间概览
    """
    try:
        if start_time >= end_time:
            raise APIException("起始时间必须早于结束时间", code=400)

        result = await AnalyticsService.get_overview(
            start_time=start_time,
            end_time=end_time,
            bot_id=bot_id,
        )
        return success_response(data=result)
    except APIException:
        raise
    except Exception as e:
        raise APIException(f"获取区间概览失败：{e!s}", code=500)


@router.get(
    "/heatmap",
    response_model=APIResponse[MessageHeatmap],
    response_class=JSONResponse,
    summary="获取消息热力图（星期 × 小时）",
)
async def get_heatmap(
    user: AuthenticatedUser,
    start_time: datetime = Query(..., description="起始时间 (ISO 格式)"),
    end_time: datetime = Query(..., description="结束时间 (ISO 格式)"),
    bot_id: str | None = Query(None, description="Bot ID"),
) -> APIResponse[MessageHeatmap]:
    """获取消息热力图

    按「星期 × 小时」聚合消息量，用于观察 bot 活跃时段。

    Args:
        start_time: 起始时间 (ISO 格式)
        end_time: 结束时间 (ISO 格式)
        bot_id: Bot ID，可选

    Returns:
        APIResponse[MessageHeatmap]: 7×24 热力矩阵
    """
    try:
        if start_time >= end_time:
            raise APIException("起始时间必须早于结束时间", code=400)

        result = await AnalyticsService.get_heatmap(
            start_time=start_time,
            end_time=end_time,
            bot_id=bot_id,
        )
        return success_response(data=result)
    except APIException:
        raise
    except Exception as e:
        raise APIException(f"获取热力图失败：{e!s}", code=500)


@router.get(
    "/trend",
    response_model=APIResponse[TrendData],
    response_class=JSONResponse,
    summary="获取趋势数据",
)
async def get_trend_data(
    user: AuthenticatedUser,
    start_time: datetime = Query(..., description="起始时间 (ISO 格式)"),
    end_time: datetime = Query(..., description="结束时间 (ISO 格式)"),
    granularity: str = Query("day", description="时间粒度：hour/day/week/month"),
    bot_id: str | None = Query(None, description="Bot ID"),
) -> APIResponse[TrendData]:
    """获取趋势数据

    按指定时间粒度返回消息数量和插件调用次数的趋势数据。

    Args:
        start_time: 起始时间 (ISO 格式)
        end_time: 结束时间 (ISO 格式)
        granularity: 时间粒度 (hour/day/week/month)
        bot_id: Bot ID，可选

    Returns:
        APIResponse[TrendData]: 趋势数据
    """
    try:
        # 验证时间范围
        if start_time >= end_time:
            raise APIException("起始时间必须早于结束时间", code=400)

        # 验证时间粒度
        valid_granularities = ["hour", "day", "week", "month"]
        if granularity not in valid_granularities:
            raise APIException(
                f"无效的时间粒度，有效值：{', '.join(valid_granularities)}", code=400
            )

        result = await AnalyticsService.get_trend_data(
            start_time=start_time,
            end_time=end_time,
            granularity=granularity,  # type: ignore
            bot_id=bot_id,
        )
        return success_response(data=result)
    except APIException:
        raise
    except Exception as e:
        raise APIException(f"获取趋势数据失败：{e!s}", code=500)


@router.get(
    "/statistics",
    response_model=APIResponse[DetailedStatisticsTimeRange],
    response_class=JSONResponse,
    summary="获取详细统计（带时间范围）",
)
async def get_statistics(
    user: AuthenticatedUser,
    start_time: datetime = Query(..., description="起始时间 (ISO 格式)"),
    end_time: datetime = Query(..., description="结束时间 (ISO 格式)"),
    bot_id: str | None = Query(None, description="Bot ID"),
) -> APIResponse[DetailedStatisticsTimeRange]:
    """获取详细统计数据

    返回指定时间范围内的群组/好友消息和插件调用统计。

    Args:
        start_time: 起始时间 (ISO 格式)
        end_time: 结束时间 (ISO 格式)
        bot_id: Bot ID，可选

    Returns:
        APIResponse[DetailedStatisticsTimeRange]: 详细统计数据
    """
    try:
        # 验证时间范围
        if start_time >= end_time:
            raise APIException("起始时间必须早于结束时间", code=400)

        result = await AnalyticsService.get_detailed_statistics(
            start_time=start_time,
            end_time=end_time,
            bot_id=bot_id,
        )
        return success_response(data=result)
    except APIException:
        raise
    except Exception as e:
        raise APIException(f"获取详细统计数据失败：{e!s}", code=500)


@router.get(
    "/favorability-top10",
    response_model=APIResponse[list[FavorabilityRank]],
    response_class=JSONResponse,
    summary="获取好感度 top10",
)
async def get_favorability_top10(
    user: AuthenticatedUser,
    bot_id: str | None = Query(None, description="Bot ID"),
) -> APIResponse[list[FavorabilityRank]]:
    """获取好感度 top10 用户

    Args:
        bot_id: Bot ID，可选

    Returns:
        APIResponse[list[FavorabilityRank]]: 好感度排名列表
    """
    try:
        result = await AnalyticsService.get_favorability_top10(bot_id)
        return success_response(data=result)
    except APIException:
        raise
    except Exception as e:
        raise APIException(f"获取好感度排名失败：{e!s}", code=500)


@router.get(
    "/gold-top10",
    response_model=APIResponse[list[GoldRank]],
    response_class=JSONResponse,
    summary="获取金币 top10",
)
async def get_gold_top10(
    user: AuthenticatedUser,
    bot_id: str | None = Query(None, description="Bot ID"),
) -> APIResponse[list[GoldRank]]:
    """获取金币 top10 用户

    Args:
        bot_id: Bot ID，可选

    Returns:
        APIResponse[list[GoldRank]]: 金币排名列表
    """
    try:
        result = await AnalyticsService.get_gold_top10(bot_id)
        return success_response(data=result)
    except APIException:
        raise
    except Exception as e:
        raise APIException(f"获取金币排名失败：{e!s}", code=500)
