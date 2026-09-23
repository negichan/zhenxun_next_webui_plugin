"""管理相关模型"""
from pydantic import BaseModel, Field


class GroupMember(BaseModel):
    """群成员信息"""

    user_id: str = Field(..., description="用户 ID")
    nickname: str = Field(..., description="昵称")
    remark: str = Field("", description="群名片")
    ava_url: str = Field(..., description="头像 URL")
    role: str = Field("member", description="角色：member/admin/owner")


class MemberDetail(BaseModel):
    """成员详情（含金币、好感度）"""

    user_id: str = Field(..., description="用户 ID")
    nickname: str = Field(..., description="昵称")
    remark: str = Field("", description="群名片")
    ava_url: str = Field(..., description="头像 URL")
    gold: int = Field(0, description="金币数量")
    favorability: int = Field(0, description="好感度/权限等级")
    is_banned: bool = Field(False, description="是否被禁用")


class GroupDetail(BaseModel):
    """群组详情"""

    group_id: str = Field(..., description="群组 ID")
    group_name: str = Field(..., description="群组名称")
    ava_url: str = Field(..., description="群头像 URL")
    member_count: int = Field(0, description="成员数量")
    max_member_count: int = Field(0, description="最大成员数")
    level: int = Field(5, description="群权限等级")
    status: bool = Field(True, description="群状态")
    is_super: bool = Field(False, description="是否超级用户指定群")
    block_task: bool = Field(False, description="是否禁用被动任务")
    block_plugin: bool = Field(False, description="是否禁用插件")


class UpdateGroupRequest(BaseModel):
    """更新群组请求"""

    group_id: str = Field(..., description="群组 ID")
    status: bool | None = Field(None, description="群状态")
    level: int | None = Field(None, description="群权限等级")
    block_task: bool | None = Field(None, description="是否禁用被动任务")
    block_plugin: bool | None = Field(None, description="是否禁用插件")
    is_super: bool | None = Field(None, description="是否超级用户指定群")


class UpdateMemberRequest(BaseModel):
    """更新成员请求"""

    user_id: str = Field(..., description="用户 ID")
    group_id: str = Field(..., description="群组 ID")
    gold: int | None = Field(None, description="金币数量")
    favorability: int | None = Field(None, description="好感度/权限等级")
    is_banned: bool | None = Field(None, description="是否被禁用")


class TogglePluginRequest(BaseModel):
    """切换插件请求"""

    group_id: str = Field(..., description="群组 ID")
    module: str = Field(..., description="插件模块名")
    action: str = Field(..., description="操作：block/unblock")
    is_task: bool = Field(False, description="是否为被动任务")


class GroupStatistics(BaseModel):
    """群数据统计"""

    group_id: str = Field(..., description="群组 ID")
    group_name: str = Field(..., description="群组名称")
    chat_count: int = Field(0, description="发言数量")
    call_count: int = Field(0, description="插件调用数量")
    member_count: int = Field(0, description="成员数量")
    active_members: int = Field(0, description="活跃成员数")


class LeaveGroupRequest(BaseModel):
    """退群请求"""

    bot_id: str = Field(..., description="Bot ID")
    group_id: str = Field(..., description="群组 ID")


class DeleteFriendRequest(BaseModel):
    """移除好友请求"""

    bot_id: str = Field(..., description="Bot ID")
    user_id: str = Field(..., description="用户 ID")


class GroupRenameRequest(BaseModel):
    """修改群名请求（OneBot set_group_name）"""

    bot_id: str = Field(..., description="Bot ID")
    group_id: str = Field(..., description="群组 ID")
    group_name: str = Field(..., min_length=1, description="新群名")


class FriendRemarkRequest(BaseModel):
    """设置好友备注请求（OneBot 扩展 set_friend_remark）"""

    bot_id: str = Field(..., description="Bot ID")
    user_id: str = Field(..., description="用户 ID")
    remark: str = Field("", description="备注内容")


class AddBlacklistRequest(BaseModel):
    """添加黑名单请求"""

    user_id: str = Field(..., description="用户 ID")
    group_id: str = Field(..., description="群组 ID")
    reason: str = Field("", description="拉黑原因")


class RemoveBlacklistRequest(BaseModel):
    """移除黑名单请求"""

    user_id: str = Field(..., description="用户 ID")
    group_id: str = Field(..., description="群组 ID")


class FriendRequestResult(BaseModel):
    """好友请求结果"""

    bot_id: str = Field(..., description="Bot ID")
    oid: int = Field(..., description="请求 ID")
    id: str = Field(..., description="用户 ID")
    flag: str = Field(..., description="请求 flag")
    nickname: str | None = Field(None, description="昵称")
    comment: str | None = Field(None, description="备注信息")
    ava_url: str = Field(..., description="头像 URL")
    type: str = Field("friend", description="请求类型")


class GroupRequestResult(BaseModel):
    """群组请求结果"""

    bot_id: str = Field(..., description="Bot ID")
    oid: int = Field(..., description="请求 ID")
    id: str = Field(..., description="用户 ID")
    flag: str = Field(..., description="请求 flag")
    nickname: str | None = Field(None, description="昵称")
    comment: str | None = Field(None, description="备注信息")
    ava_url: str = Field(..., description="头像 URL")
    type: str = Field("group", description="请求类型")
    invite_group: str = Field(..., description="邀请群组 ID")
    group_name: str | None = Field(None, description="群组名称")


class ReqResult(BaseModel):
    """请求结果"""

    friend: list[FriendRequestResult] = Field(default_factory=list, description="好友请求列表")
    group: list[GroupRequestResult] = Field(default_factory=list, description="群组请求列表")


class HandleRequest(BaseModel):
    """处理请求"""

    bot_id: str | None = Field(None, description="Bot ID")
    id: int = Field(..., description="请求 ID")
    action: str = Field("approve", description="操作类型：approve/refused/ignore")


class ClearRequest(BaseModel):
    """清空请求"""

    request_type: str = Field(..., description="请求类型：friend/group")


class FriendDetail(BaseModel):
    """好友详情"""

    user_id: str = Field(..., description="用户 ID")
    nickname: str = Field(..., description="昵称")
    ava_url: str = Field(..., description="头像 URL")
    gold: int = Field(0, description="金币数量")
    favorability: float = Field(0.0, description="好感度")


class UpdateFriendRequest(BaseModel):
    """更新好友数据请求"""

    user_id: str = Field(..., description="用户 ID")
    gold: int | None = Field(None, description="金币数量")
    favorability: float | None = Field(None, description="好感度")


class FriendTrendPoint(BaseModel):
    """好友趋势数据点"""

    date: str = Field(..., description="日期 MM-DD")
    chat_count: int = Field(0, description="聊天消息数")
    call_count: int = Field(0, description="插件调用数")


class FriendTrend(BaseModel):
    """好友趋势数据"""

    data: list[FriendTrendPoint] = Field(default_factory=list, description="趋势数据点")
    total_chat: int = Field(0, description="总聊天数")
    total_call: int = Field(0, description="总调用数")
