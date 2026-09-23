"""管理相关路由"""
from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from ..dependencies import AuthenticatedUser
from ..models.manage import (
    AddBlacklistRequest,
    ClearRequest,
    DeleteFriendRequest,
    FriendDetail,
    FriendRemarkRequest,
    FriendTrend,
    GroupDetail,
    GroupRenameRequest,
    GroupStatistics,
    HandleRequest,
    LeaveGroupRequest,
    MemberDetail,
    RemoveBlacklistRequest,
    TogglePluginRequest,
    UpdateFriendRequest,
    UpdateGroupRequest,
    UpdateMemberRequest,
)
from ..models.system import Friend, Group
from ..responses import APIResponse, error_response, success_response
from ..services.manage_service import ManageService

router = APIRouter(prefix="/manage", tags=["管理"])


@router.get(
    "/friend-list",
    response_model=APIResponse[list[Friend]],
    response_class=JSONResponse,
    summary="获取好友列表",
)
async def get_friend_list(
    user: AuthenticatedUser, bot_id: str | None = None
) -> APIResponse[list[Friend]]:
    """获取好友列表"""
    result = await ManageService.get_friend_list(bot_id)
    return success_response(data=result)


@router.get(
    "/group-list",
    response_model=APIResponse[list[Group]],
    response_class=JSONResponse,
    summary="获取群组列表",
)
async def get_group_list(
    user: AuthenticatedUser, bot_id: str | None = None
) -> APIResponse[list[Group]]:
    """获取群组列表"""
    result = await ManageService.get_group_list(bot_id)
    return success_response(data=result)


@router.post(
    "/send-message",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="发送消息",
)
async def send_message(
    user: AuthenticatedUser, request: dict
) -> APIResponse[bool]:
    """发送消息"""
    from pydantic import BaseModel

    class SendMessageRequest(BaseModel):
        bot_id: str
        user_id: str | None = None
        group_id: str | None = None
        message: str

    req = SendMessageRequest(**request)
    result = await ManageService.send_message(
        bot_id=req.bot_id,
        user_id=req.user_id,
        group_id=req.group_id,
        message=req.message,
    )
    return success_response(data=result)


@router.post(
    "/leave-group",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="退群",
)
async def leave_group(
    user: AuthenticatedUser, request: LeaveGroupRequest
) -> APIResponse[bool]:
    """退群"""
    result = await ManageService.leave_group(
        bot_id=request.bot_id, group_id=request.group_id
    )
    if not result:
        return error_response(
            message="退群失败：协议端不支持该操作或群组不存在"
        )
    return success_response(data=result)


@router.post(
    "/delete-friend",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="移除好友",
)
async def delete_friend(
    user: AuthenticatedUser, request: DeleteFriendRequest
) -> APIResponse[bool]:
    """移除好友"""
    result = await ManageService.delete_friend(
        bot_id=request.bot_id, user_id=request.user_id
    )
    if not result:
        return error_response(
            message="移除好友失败：协议端不支持该操作或好友不存在"
        )
    return success_response(data=result)


@router.post(
    "/group/rename",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="修改群名",
)
async def rename_group(
    user: AuthenticatedUser, request: GroupRenameRequest
) -> APIResponse[bool]:
    """通过 OneBot 修改群名"""
    result = await ManageService.rename_group(
        bot_id=request.bot_id,
        group_id=request.group_id,
        group_name=request.group_name,
    )
    if not result:
        return error_response(
            message="修改群名失败：协议端不支持该操作或群组不存在"
        )
    return success_response(data=result)


@router.post(
    "/friend/remark",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="设置好友备注",
)
async def set_friend_remark(
    user: AuthenticatedUser, request: FriendRemarkRequest
) -> APIResponse[bool]:
    """通过 OneBot 扩展接口设置好友备注"""
    result = await ManageService.set_friend_remark(
        bot_id=request.bot_id,
        user_id=request.user_id,
        remark=request.remark,
    )
    if not result:
        return error_response(
            message="设置备注失败：协议端不支持 set_friend_remark 扩展接口"
        )
    return success_response(data=result)


@router.get(
    "/group-detail",
    response_model=APIResponse[GroupDetail | None],
    response_class=JSONResponse,
    summary="获取群组详情",
)
async def get_group_detail(
    user: AuthenticatedUser, group_id: str, bot_id: str | None = None
) -> APIResponse[GroupDetail | None]:
    """获取群组详情"""
    result = await ManageService.get_group_detail(bot_id, group_id)
    return success_response(data=result)


@router.post(
    "/update-group",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="更新群组设置",
)
async def update_group(
    user: AuthenticatedUser, request: UpdateGroupRequest
) -> APIResponse[bool]:
    """更新群组设置"""
    result = await ManageService.update_group(request)
    return success_response(data=result)


@router.get(
    "/group-members",
    response_model=APIResponse[list[dict]],
    response_class=JSONResponse,
    summary="获取群成员列表",
)
async def get_group_members(
    user: AuthenticatedUser, group_id: str, bot_id: str | None = None
) -> APIResponse[list[dict]]:
    """获取群成员列表"""
    result = await ManageService.get_group_members(bot_id, group_id)
    return success_response(
        data=[m.model_dump() if hasattr(m, "model_dump") else m for m in result]
    )


@router.get(
    "/member-detail",
    response_model=APIResponse[MemberDetail | None],
    response_class=JSONResponse,
    summary="获取成员详情",
)
async def get_member_detail(
    user: AuthenticatedUser, user_id: str, group_id: str
) -> APIResponse[MemberDetail | None]:
    """获取成员详情"""
    result = await ManageService.get_member_detail(group_id, user_id)
    return success_response(data=result)


@router.post(
    "/update-member",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="更新成员数据",
)
async def update_member(
    user: AuthenticatedUser, request: UpdateMemberRequest
) -> APIResponse[bool]:
    """更新成员数据"""
    result = await ManageService.update_member(request)
    return success_response(data=result)


@router.get(
    "/group-plugins",
    response_model=APIResponse[list[dict]],
    response_class=JSONResponse,
    summary="获取群功能开关列表",
)
async def get_group_plugins(
    user: AuthenticatedUser, group_id: str
) -> APIResponse[list[dict]]:
    """获取群功能开关列表"""
    result = await ManageService.get_group_plugins(group_id)
    return success_response(data=result)


@router.post(
    "/toggle-group-plugin",
    response_model=APIResponse[dict],
    response_class=JSONResponse,
    summary="切换群功能开关",
)
async def toggle_group_plugin(
    user: AuthenticatedUser, request: TogglePluginRequest
) -> APIResponse[dict]:
    """切换群功能开关"""
    result = await ManageService.toggle_group_plugin(request)
    return success_response(data=result)


@router.get(
    "/group-statistics",
    response_model=APIResponse[GroupStatistics | None],
    response_class=JSONResponse,
    summary="获取群数据统计",
)
async def get_group_statistics(
    user: AuthenticatedUser, group_id: str, bot_id: str | None = None
) -> APIResponse[GroupStatistics | None]:
    """获取群数据统计"""
    result = await ManageService.get_group_statistics(bot_id, group_id)
    return success_response(data=result)


@router.get(
    "/blacklist",
    response_model=APIResponse[list[dict]],
    response_class=JSONResponse,
    summary="获取群黑名单列表",
)
async def get_blacklist(
    user: AuthenticatedUser, group_id: str
) -> APIResponse[list[dict]]:
    """获取群黑名单列表"""
    # TODO: 实现黑名单获取逻辑
    return success_response(data=[])


@router.post(
    "/add-blacklist",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="添加群成员黑名单",
)
async def add_blacklist(
    user: AuthenticatedUser, request: AddBlacklistRequest
) -> APIResponse[bool]:
    """添加群成员黑名单"""
    # TODO: 实现黑名单添加逻辑
    return success_response(data=True)


@router.post(
    "/remove-blacklist",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="移除黑名单",
)
async def remove_blacklist(
    user: AuthenticatedUser, request: RemoveBlacklistRequest
) -> APIResponse[bool]:
    """移除黑名单"""
    # TODO: 实现黑名单移除逻辑
    return success_response(data=True)


@router.get(
    "/plugin-permissions",
    response_model=APIResponse[list[dict]],
    response_class=JSONResponse,
    summary="获取插件权限配置",
)
async def get_plugin_permissions(
    user: AuthenticatedUser, group_id: str
) -> APIResponse[list[dict]]:
    """获取插件权限配置"""
    # TODO: 实现插件权限获取逻辑
    return success_response(data=[])


@router.post(
    "/update-plugin-permissions",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="更新插件权限",
)
async def update_plugin_permissions(
    user: AuthenticatedUser, request: dict
) -> APIResponse[bool]:
    """更新插件权限"""
    # TODO: 实现插件权限更新逻辑
    return success_response(data=True)


@router.get(
    "/request-list",
    response_class=JSONResponse,
    summary="获取请求列表",
)
async def get_request_list(
    user: AuthenticatedUser, bot_id: str | None = None
):
    """获取请求列表"""
    result = await ManageService.get_request_list(bot_id)
    return success_response(data=result)


@router.post(
    "/handle-request",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="处理请求",
)
async def handle_request(
    user: AuthenticatedUser, request: HandleRequest
) -> APIResponse[bool]:
    """处理请求"""
    result = await ManageService.handle_request(
        bot_id=request.bot_id,
        request_id=request.id,
        action=request.action
    )
    return success_response(data=result)


@router.post(
    "/clear-request",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="清空请求",
)
async def clear_request(
    user: AuthenticatedUser, request: ClearRequest
) -> APIResponse[bool]:
    """清空请求"""
    result = await ManageService.clear_request(request.request_type)
    return success_response(data=result)


@router.get(
    "/friend-detail",
    response_model=APIResponse[FriendDetail | None],
    response_class=JSONResponse,
    summary="获取好友详情",
)
async def get_friend_detail(
    user: AuthenticatedUser, user_id: str,bot_id:str
) -> APIResponse[FriendDetail | None]:
    """获取好友详情（金币、好感度）"""
    result = await ManageService.get_friend_detail(user_id,bot_id)
    return success_response(data=result)


@router.post(
    "/update-friend",
    response_model=APIResponse[bool],
    response_class=JSONResponse,
    summary="更新好友数据",
)
async def update_friend(
    user: AuthenticatedUser, request: UpdateFriendRequest
) -> APIResponse[bool]:
    """更新好友数据（金币、好感度）"""
    result = await ManageService.update_friend(request)
    return success_response(data=result)


@router.get(
    "/friend-trend",
    response_model=APIResponse[FriendTrend],
    response_class=JSONResponse,
    summary="获取好友趋势数据",
)
async def get_friend_trend(
    user: AuthenticatedUser, user_id: str, days: int = Query(default=7, ge=1, le=90)
) -> APIResponse[FriendTrend]:
    """获取好友近 N 天私聊趋势数据"""
    result = await ManageService.get_friend_trend(user_id, days)
    return success_response(data=result)
