# WhaleBot

使用 **AstrBot + SnowLuma** 构建本地 Docker QQ 聊天机器人。SnowLuma 负责 QQ 接入和消息收发，AstrBot 负责指令、模型调用与插件。

```text
手机 QQ / QQ 群
      ↕
容器中的 QQ ↔ SnowLuma ── 反向 WebSocket ──→ AstrBot ↔ 模型服务
                         ws://astrbot:6199/ws
```

## 部署配置

| 组件 | 镜像 / 配置 |
| --- | --- |
| AstrBot | `soulter/astrbot:latest` |
| SnowLuma | `motricseven7/snowluma:v2.2.1` |
| 容器管理 | Docker Compose，项目名 `whalebot` |
| Windows 后端 | Docker Desktop + WSL2，Linux containers |
| 时区 | `Asia/Shanghai` |
| 数据保存 | 四个 Docker 命名卷 |

上述为仓库默认值，实际部署以本机 `.env` 为准。AstrBot 的 `latest` 标签会变化，可在验证后固定为版本标签或镜像摘要。

本机已完成两个服务的部署及 OneBot 配置。**首次在其他电脑部署时，仍需按下文登录 QQ、配置双方连接并接入模型**；这些运行配置保存在数据卷内，不会随 Git 仓库自动复制。

## 一键启动（Windows）

双击项目根目录的 **[Start-WhaleBot.cmd](Start-WhaleBot.cmd)** 即可。启动器会自动查找并启动 Docker Desktop、等待 Linux 容器引擎就绪，然后启动 AstrBot 和 SnowLuma，检查页面响应并打开两个管理面板及 QQ 远程桌面。

首次使用仍需安装 Docker Desktop。没有 `.env` 时，启动器会从示例创建配置；远程桌面密码为空时，会自动生成并保存到 `.env` 的 `VNC_PASSWD`。现有非空密码会保留。缺失的镜像会在启动容器时下载，已有镜像不会主动更新。

QQ 扫码登录、首次面板设置和模型配置仍需手动完成；启动成功表示本地服务就绪。重复双击可恢复已停止的容器，不会主动重启正常运行的容器。

启动失败时窗口会保留错误信息。排查 Docker Desktop 的提示后重新运行即可。也可以在 PowerShell 中启动而不打开浏览器：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\Start-WhaleBot.ps1 -NoBrowser
```

## 手动启动

### 1. 检查 Docker

Windows 安装并启动 [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)，启用 WSL2 后端，使用 Linux containers。

在项目目录打开 PowerShell：

```powershell
docker info
docker compose version
```

### 2. 配置环境

仅首次部署执行：

```powershell
Copy-Item .env.example .env
```

编辑 `.env`，为 `VNC_PASSWD` 设置独立的 8 位密码。已有 `.env` 时保留原文件。

| 环境变量 | 默认值 / 用途 |
| --- | --- |
| `ASTRBOT_IMAGE` | `soulter/astrbot:latest` |
| `SNOWLUMA_IMAGE` | `motricseven7/snowluma:v2.2.1` |
| `TZ` | `Asia/Shanghai` |
| `ASTRBOT_WEBUI_PORT` | AstrBot 面板：`6185` |
| `SNOWLUMA_WEBUI_PORT` | SnowLuma 面板：`5099` |
| `NOVNC_PORT` | QQ 远程桌面：`6081` |
| `ONEBOT_WS_PORT` | SnowLuma WS 服务端：`3001` |
| `VNC_PASSWD` | QQ 远程桌面密码，必须填写 |

### 3. 启动容器

```powershell
docker compose config --quiet
docker compose pull
docker compose up -d
docker compose ps
```

本项目直接使用上游镜像，无需本地构建。首次拉取需要下载 QQ 客户端及运行环境，可能耗时较长。

## 访问与登录

| 入口 | 默认地址 | 登录凭据 |
| --- | --- | --- |
| AstrBot 面板 | [打开面板](http://127.0.0.1:6185/) | 初始用户名、密码见 AstrBot 启动日志 |
| SnowLuma 面板 | [打开面板](http://127.0.0.1:5099/) | 初始凭据见 SnowLuma 启动日志；登录页可能显示“访问令牌” |
| QQ 远程桌面 | [打开桌面](http://127.0.0.1:6081/) | `.env` 中的 `VNC_PASSWD` |
| SnowLuma WS 服务端 | `ws://127.0.0.1:3001/` | 对应 WS 服务端配置中的 `Access Token` |

修改 `.env` 中的端口后，请相应调整访问地址。所有宿主机端口均绑定 `127.0.0.1`，仅允许本机访问。

查看初始登录凭据：

```powershell
docker compose logs --tail 200 astrbot
docker compose logs --tail 200 snowluma
```

初始密码通常仅在首次初始化时输出。登录后修改初始密码；已修改时使用新密码。不要将包含密码或令牌的日志公开分享。

### 登录 QQ

1. 打开 QQ 远程桌面，点击 **Connect / 连接**。
2. 输入 `.env` 中的 `VNC_PASSWD`。
3. 在容器内 QQ 窗口选择扫码登录，用手机 QQ 扫描并确认。
4. 回到 SnowLuma 面板，确认 QQ 账号在线；首次使用时按页面提示阅读并确认相关条款。

二维码过期时刷新二维码。容器重启后若显示等待登录，请重新进入桌面确认登录。

## 配置 SnowLuma 与 AstrBot 连接

AstrBot 使用 **OneBot v11 反向 WebSocket**：AstrBot 监听连接，SnowLuma 作为 WS 客户端主动连接它。SnowLuma 的 WS 服务端可供其他 OneBot 客户端使用。

### 1. 生成连接令牌

首次配置可在 PowerShell 中生成随机令牌，将同一值填入 AstrBot 和 SnowLuma 的反向连接配置：

```powershell
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$bytes = New-Object byte[] 32
$rng.GetBytes($bytes)
$rng.Dispose()
[BitConverter]::ToString($bytes).Replace('-', '').ToLowerInvariant()
```

**已有连接正常时，无需重新生成令牌。** 面板登录凭据、远程桌面密码、WS 服务端令牌和反向连接令牌分别管理；反向连接两端的令牌必须一致。

### 2. AstrBot：添加 OneBot v11

在消息平台管理中添加适配器：

| 配置项 | 值 |
| --- | --- |
| ID | `qq-snowluma` |
| 类型 | OneBot v11（内部类型 `aiocqhttp`） |
| 启用 | 是 |
| 反向 WebSocket 主机 | `0.0.0.0` |
| 反向 WebSocket 端口 | `6199` |
| Token | 双方共用的连接令牌 |

### 3. SnowLuma：添加 WS 客户端

在面板中选择**已登录的 QQ 账号**，进入网络配置，添加或编辑 WS 客户端（反向 WebSocket）：

| 配置项 | 值 |
| --- | --- |
| 名称 | `astrbot` |
| 启用 | 是 |
| URL | `ws://astrbot:6199/ws` |
| Access Token | 与 AstrBot 的 Token 一致 |
| Role | `Universal` |
| 消息格式 | `array` |
| 上报自身消息 | 关闭 |
| 重连间隔 | `5000` 毫秒 |

容器内的 `127.0.0.1` 指向该容器自身，连接 AstrBot 时必须使用 Compose 服务名 `astrbot`。6199 端口仅在容器网络内使用，无需发布到 Windows。

### 4. SnowLuma：配置 WS 服务端

已有 `ws-default` 时直接编辑，避免创建占用相同端口的重复服务端：

| 配置项 | 值 |
| --- | --- |
| 名称 | `ws-default` |
| 启用 | 是 |
| 监听主机 | `0.0.0.0` |
| 端口 / 路径 | `3001` / `/` |
| Role | `Universal` |
| Access Token | 服务端独立令牌，供连接它的客户端使用 |
| 消息格式 | `array` |
| 上报自身消息 | 关闭 |

本机客户端连接 `ws://127.0.0.1:3001/`，同一 Compose 网络内的客户端连接 `ws://snowluma:3001/`。这是另一条连接入口，AstrBot 使用上面的反向连接。

保存后检查日志；若配置未生效，可重启对应服务：

```powershell
docker compose restart astrbot snowluma
docker compose logs --tail 100 -f astrbot snowluma
```

QQ 在线且 AstrBot 日志显示 OneBot 适配器连接成功，才算完成连接。仅看到容器运行或端口可达，还需要继续验证消息收发。

手工配置参考：[examples/onebot.example.json](examples/onebot.example.json)。该示例仅包含 WS 客户端，不会自动加载。使用前替换令牌占位符，备份后将条目合并到账号配置，保留其他已有字段。账号配置位于 SnowLuma 容器的 `/app/data/config/onebot_<QQ号>.json`，优先通过面板修改。

## 接入模型与验收

1. 在 AstrBot 模型服务页面添加服务商，填写 API 地址、API Key 和模型名。
2. 将该模型设为机器人配置使用的聊天模型并保存。
3. QQ 私聊发送 `/help`，确认指令可以返回。
4. 私聊发送问候语，验证模型回复。
5. 群聊通过 `@机器人 你好` 验证，按需调整唤醒方式、管理员和会话权限。

模型密钥保存在本地管理配置中，不填写到 README 或示例文件。

## 日常维护

```powershell
# 查看状态
docker compose ps

# AstrBot 日志（Docker Desktop 中也可选择容器 → Logs）
docker compose logs --tail 100 -f astrbot

# SnowLuma 日志
docker compose logs --tail 100 -f snowluma

# 停止 / 恢复，保留数据
docker compose stop
docker compose start

# 修改 .env 后重新应用配置
docker compose up -d
```

容器默认使用 `unless-stopped` 重启策略。按 `Ctrl+C` 可退出日志查看，不会停止容器。

### 数据位置

| 命名卷 | 容器内目录 | 内容 |
| --- | --- | --- |
| `whalebot_astrbot-data` | `/AstrBot/data` | AstrBot 配置、模型设置、插件及运行数据 |
| `whalebot_snowluma-data` | `/app/data` | SnowLuma 配置、面板凭据及缓存 |
| `whalebot_qq-client-config` | `/app/.config` | QQ 配置与账号数据 |
| `whalebot_qq-client-data` | `/app/.local/share` | QQ 本地数据 |

卷名基于当前 Compose 项目名 `whalebot`。这些数据位于 Docker 管理的卷内，不在仓库的普通文件夹中。

本机已于 2026-10-28 通过 Docker Desktop 官方设置将数据磁盘迁移至 `D:\DockerData\DockerDesktopWSL`，主要文件为 `disk\docker_data.vhdx`。镜像、容器文件和命名卷均存储在该磁盘内；Docker Desktop 安装程序及少量用户设置仍在 C 盘。新电脑上的存储位置以 Docker Desktop 设置为准。

此次迁移前的四个数据卷备份与核验记录保存在 `backups/before-docker-move-20261028-183926/`。迁移后已核对配置文件哈希、会话和记忆数据库的表记录数及完整性。今后变更存储目录请使用 Docker Desktop 的磁盘位置设置，不要直接移动正在使用的虚拟磁盘文件。

`.env`、`backups/` 和日志文件已加入 Git 忽略规则。实际凭据不写入仓库。`docker compose down` 保留数据卷；**`docker compose down -v` 会删除数据卷**。

### 更新与备份

1. 更新前停止 SnowLuma，并备份它的三个数据卷；更新 AstrBot 时也备份其数据卷。备份本机 `.env` 和 `compose.yaml`。
2. 修改 `.env` 中目标镜像的版本标签，核对该版本的数据目录要求。
3. 拉取并重建对应服务。例如仅更新 SnowLuma：

```powershell
docker compose pull snowluma
docker compose up -d snowluma
```

4. 检查面板、QQ 登录状态、OneBot 连接和实际消息回复。

本机从 v1.10.0 升级到 v2.2.1 前的配置和数据备份位于 `backups/before-snowluma-v2.2.1/`，其中 `snowluma-and-qq.tar.gz` 包含旧版 SnowLuma 与 QQ 的三个数据目录。备份包含登录凭据，应妥善保存。

v2.2.1 已将应用数据目录统一为 `/app/data`，并包含配置权限修复，无需旧版 `snowluma-init` 服务。回滚旧版时需同时恢复旧配置与相应数据备份，不能只修改镜像标签。

## 常见问题

| 问题 | 检查方法 |
| --- | --- |
| 找不到 `docker` 命令 | 安装 Docker Desktop 后重新打开终端 |
| 无法连接 Docker 引擎 | 启动 Docker Desktop，确认 WSL2 后端和 Linux containers 可用 |
| 镜像拉取失败 | 检查 Docker 网络、代理及镜像标签 |
| 面板打不开 | 查看 `docker compose ps`、对应日志与本机端口占用 |
| SnowLuma 登录页提示密码错误 | 使用面板登录凭据；桌面密码 `VNC_PASSWD` 和 OneBot 令牌用于其他入口 |
| 找不到初始面板密码 | 查看对应服务的首次启动日志；已修改时使用新密码 |
| QQ 桌面显示等待登录 | 进入 6081 端口的桌面扫码或确认登录 |
| OneBot 未连接 | 确认 QQ 在线、双方令牌一致、URL 使用 `astrbot:6199/ws`，且适配器已启用 |
| WS 服务端连接失败 | 检查 QQ 在线状态、3001 端口映射和服务端令牌 |
| 指令有回复但模型无回复 | 检查聊天模型选择、模型服务凭据和 AstrBot 错误日志 |
| 群里没有回复 | 尝试 @机器人，检查唤醒配置及会话权限 |

## 官方资料

- [AstrBot Docker 部署](https://docs.astrbot.app/deploy/astrbot/docker.html)
- [AstrBot OneBot v11 接入](https://github.com/AstrBotDevs/AstrBot/wiki/en-platform-aiocqhttp)
- [SnowLuma v2.2.1 发布页](https://github.com/SnowLuma/SnowLuma/releases/tag/v2.2.1)
- [SnowLuma Docker 部署](https://snowluma.github.io/zh/docs/guide/deploy/docker)
- [SnowLuma Windows Docker Desktop 部署](https://snowluma.github.io/zh/docs/guide/deploy/windows-docker)
- [SnowLuma 对接机器人](https://snowluma.github.io/zh/docs/guide/connect-bot)
- [SnowLuma 配置参考](https://snowluma.github.io/zh/docs/guide/configuration)
- [SnowLuma 持久化数据迁移](https://snowluma.github.io/zh/docs/guide/deploy/storage-migration)
