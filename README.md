# zhenxun WebUI 后端插件

真寻机器人（[zhenxun_bot](https://github.com/psxchen/zhenxun_bot)）的 Web 控制台后端，重构版。为管理面板与聊天页提供 HTTP / WebSocket 接口，并托管前端构建产物。

需搭配前端仓库使用：[negichan/zhenxun_new_webui](https://github.com/negichan/zhenxun_new_webui)。

## 安装

作为 zhenxun 插件安装，二选一：

1. 通过真寻的插件管理器安装；
2. 手动将本仓库放入 `zhenxun/plugins/` 目录，重启机器人。

> 本插件依赖 zhenxun 核心与随附的 nonebot 生态（nonebot-plugin-alconna、nonebot-plugin-uninfo 等），**不能脱离 zhenxun 独立运行**。

## 配置

插件设置项位于配置模块 `web-ui`：

| 键 | 说明 | 默认 |
| --- | --- | --- |
| `username` | 管理登录用户名 | `admin` |
| `password` | 管理登录密码 | 空（需设置） |
| `secret` | JWT 签名密钥 | 随机生成 |

首次使用请在真寻配置中设置 `password`，用 `username` + `password` 登录前端。

## 前端产物

将前端构建的 `dist` 放到插件数据目录 `data/web_ui/dist`，即挂载到 `/next`。若该目录为空，插件启动后会在后台从 GitHub Release 自动拉取，无需手动放置。

## 接口概览

- HTTP API：`/zhenxun/api/v1/*`
- WebSocket：`/zhenxun/ws/v1/{logs,status,chat,debug}`
- 交互式文档：`/docs`（FastAPI 自动生成）

## 许可

[MIT](./LICENSE)
