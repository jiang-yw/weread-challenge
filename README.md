---
license: mit
sdk: docker
app_port: 7860
---

<p align="center">
    <a href="https://linux.do" alt="LINUX DO">
        <img
            src="https://img.shields.io/badge/LINUX-DO-FFB003.svg?logo=data:image/svg%2bxml;base64,DQo8c3ZnIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyIgd2lkdGg9IjEwMCIgaGVpZ2h0PSIxMDAiPjxwYXRoIGQ9Ik00Ni44Mi0uMDU1aDYuMjVxMjMuOTY5IDIuMDYyIDM4IDIxLjQyNmM1LjI1OCA3LjY3NiA4LjIxNSAxNi4xNTYgOC44NzUgMjUuNDV2Ni4yNXEtMi4wNjQgMjMuOTY4LTIxLjQzIDM4LTExLjUxMiA3Ljg4NS0yNS40NDUgOC44NzRoLTYuMjVxLTIzLjk3LTIuMDY0LTM4LjAwNC0yMS40M1EuOTcxIDY3LjA1Ni0uMDU0IDUzLjE4di02LjQ3M0MxLjM2MiAzMC43ODEgOC41MDMgMTguMTQ4IDIxLjM3IDguODE3IDI5LjA0NyAzLjU2MiAzNy41MjcuNjA0IDQ2LjgyMS0uMDU2IiBzdHlsZT0ic3Ryb2tlOm5vbmU7ZmlsbC1ydWxlOmV2ZW5vZGQ7ZmlsbDojZWNlY2VjO2ZpbGwtb3BhY2l0eToxIi8+PHBhdGggZD0iTTQ3LjI2NiAyLjk1N3EyMi41My0uNjUgMzcuNzc3IDE1LjczOGE0OS43IDQ5LjcgMCAwIDEgNi44NjcgMTAuMTU3cS00MS45NjQuMjIyLTgzLjkzIDAgOS43NS0xOC42MTYgMzAuMDI0LTI0LjM4N2E2MSA2MSAwIDAgMSA5LjI2Mi0xLjUwOCIgc3R5bGU9InN0cm9rZTpub25lO2ZpbGwtcnVsZTpldmVub2RkO2ZpbGw6IzE5MTkxOTtmaWxsLW9wYWNpdHk6MSIvPjxwYXRoIGQ9Ik03Ljk4IDcwLjkyNmMyNy45NzctLjAzNSA1NS45NTQgMCA4My45My4xMTNRODMuNDI2IDg3LjQ3MyA2Ni4xMyA5NC4wODZxLTE4LjgxIDYuNTQ0LTM2LjgzMi0xLjg5OC0xNC4yMDMtNy4wOS0yMS4zMTctMjEuMjYyIiBzdHlsZT0ic3Ryb2tlOm5vbmU7ZmlsbC1ydWxlOmV2ZW5vZGQ7ZmlsbDojZjlhZjAwO2ZpbGwtb3BhY2l0eToxIi8+PC9zdmc+" /></a>
</p>

<h1 align="center">weread-challenge</h1>


将 [weread-challenge-selenium](https://github.com/jqknono/weread-challenge-selenium) 改造为适配 HuggingFace Spaces 的单容器版本。

## 与原项目的区别

| | 原项目 | 本项目 |
|---|---|---|
| 架构 | 双容器（app + selenium-standalone） | 单容器（内置 Chromium + Xvfb） |
| 部署 | VPS / docker-compose | HuggingFace Spaces (Docker SDK) |
| 管理 | 无 Web UI | Flask 明暗主题面板 + 密码保护 |
| 定时 | 外部 crontab | 内置 12 小时调度器 |
| 防休眠 | 无 | 自 ping /healthz |
| 持久化 | 本地目录 | HF Storage Bucket (/data) |

## 功能

- 微信读书自动刷时长（默认 68 分钟/次）
- 每 12 小时自动运行一次
- Web 管理面板：状态监控、二维码查看、手动触发、重启阅读
- 默认浅色，支持切换深色并记住浏览器内的选择；登录页使用相同主题
- 阅读设置提供中文名称、单位与用途说明；技术参数折叠展示
- 通知区只展示已有配置的渠道，可在「管理通知」编辑、启停和测试 Bark、邮件、飞书
- 日志默认展示关键事件，支持搜索、级别筛选、合并重复记录和暂停跟随，同时保留原始日志入口
- 密码保护（默认 `linux123`，可通过 `WEB_PASSWORD` 环境变量修改）
- 登录二维码实时显示 + 手动刷新
- 数据持久化到 HF Storage Bucket
- 登录失效时通过飞书群机器人 Webhook 提醒，支持签名校验、去重和测试通知

## 部署到 HuggingFace Spaces

1. 创建一个新的 Docker Space
2. 上传本项目所有文件
3. 在 Space Settings → Variables and secrets 中设置：
   - `WEB_PASSWORD`（可选，默认 `114114aa`）
   - `SECRET_KEY`（可选，Flask session 加密）
4. 创建 Storage Bucket 并挂载到 `/data`（读写模式）

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEREAD_DURATION` | 68 | 每次阅读时长（分钟） |
| `WEREAD_SPEED` | slow | 阅读速度 |
| `WEREAD_SELECTION` | 2 | 书籍选择方式 |
| `READING_INTERVAL_HOURS` | 12 | 自动阅读间隔（小时） |
| `SELF_PING_MINUTES` | 5 | 自 ping 间隔（分钟） |
| `WEB_PASSWORD` | 114114aa | Web 面板登录密码 |
| `WEBHOOK_URL` | 空 | 飞书自定义群机器人的 Webhook 地址，也可在管理面板配置 |
| `WEBHOOK_SECRET` | 空 | 飞书机器人签名校验密钥，未启用签名校验时留空 |
| `WEREAD_PANEL_URL` | 空 | 通知中的管理面板链接，填写手机可以访问的地址 |

## 飞书登录失效提醒

1. 在飞书群的设置中添加「自定义机器人」，复制 Webhook 地址。机器人若开启关键词校验，请将关键词设置为 `微信读书`；若开启签名校验，同时复制签名密钥。详见[飞书官方说明](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)。
2. 更新代码后重建镜像，并重新创建服务容器，继续挂载原来的 `weread-data:/data` 数据卷。
3. 登录 Web 管理面板，点击「管理通知」，选择「飞书」，填写 Webhook、可选的签名密钥及管理面板地址，开启此渠道并点击「保存配置」。保存后对后续登录事件生效，无需再次重启。
4. 点击「测试已保存配置」，确认群里收到 `微信读书：飞书通知测试`。测试使用已保存的配置，也可在启用前测试。

也可以通过容器环境变量配置：

```dotenv
WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/你的机器人地址
WEBHOOK_SECRET=启用签名校验时填写的密钥
WEREAD_PANEL_URL=https://你的管理面板地址
```

环境变量优先于面板的地址、账号和密钥；页面会标明并锁定这些字段。环境变量中未配置的字段才使用面板保存的值。地址和密钥在配置接口中隐藏为 `***set***`，保留该值表示不修改。启用开关由面板单独控制，即使密钥通过环境变量提供，也可以在面板停用渠道而保留凭据。

提醒由阅读程序实际检测到「需要登录」触发，包括首次未登录和 Cookie 失效。它不使用面板中根据 Cookie 文件修改时间估算的 30 天有效期。按默认调度，通常要等到下一次阅读任务（每 12 小时一次）才能发现失效；不是到期瞬间检测。

同一次登录失效成功通知后不会因二维码刷新、后续任务或容器重启重复提醒，检测到登录成功后解除去重。发送失败不会阻断阅读，同次任务的后续登录事件可重试，两次尝试至少间隔 60 秒。通知配置和去重状态保存在数据卷内；测试通知不改变去重状态。通知包含可选的管理面板链接，扫码仍在面板完成。

实现通过 `feishu_notify.py` 转发 `weread-selenium-cli` 输出，监听登录事件。升级当前固定的 CLI 0.18.0 时，应核对登录日志格式是否变化。

验证通知逻辑可运行 `python3 -m unittest discover -s tests -v`（需要 Python 3 和 Flask；可使用项目镜像运行）。测试使用本地模拟 HTTP 服务，不会向真实飞书群发送消息。

## 面板与通知管理

通知摘要显示已配置、已停用或待补全的渠道；未填写的渠道放在「管理通知」中。三个渠道均可保存配置、启停和发送测试消息。保存不会自动发送测试通知。

- 飞书：仅在阅读任务发现需要重新登录时提醒，保存后对后续登录事件生效。
- Bark：沿用阅读程序的登录和任务通知；保存后，下一次阅读任务使用新的密钥、服务器及启用状态。
- 邮件：沿用阅读程序的登录链接和任务报告；保存后，下一次阅读任务使用新的 SMTP 参数及启用状态。SMTP 授权码并非通常的邮箱登录密码；常用端口为 465 或 587。

阅读设置展示容器当前的有效参数，修改这些参数仍需重新创建容器。「上游运行统计」对应 `WEREAD_AGREE_TERMS`，开启时阅读程序会向上游项目的统计服务提交运行与微信读书用户信息。

摘要日志只读取最近 256 KB，过滤重复按键、截图大小、未配置渠道提示和上游统计详细数据，保留关键事件及异常。支持搜索、按级别筛选；关闭「跟随新日志」后，刷新会保留当前滚动位置。原始日志入口用于排查完整上下文。过期二维码不会继续展示；保存 Cookie 仅代表本地有登录信息，认证是否有效仍由实际阅读任务判断。

浏览器检查可在已有镜像中运行（需要将源码只读挂载到 `/app`；`SCRATCH_ROOT`、`TMPDIR` 指向已核实的临时目录，并设置 `WEREAD_QA_DIR` 保存截图）：

```bash
python3 tests/run_browser_checks.py
```

检查使用独立的临时登录数据和模拟通知，不启动阅读任务、不使用真实 Cookie、不向外部发送通知。覆盖登录页与面板主题切换、主题记忆、三个渠道的保存和测试、日志筛选及手机布局。

## Web 端点

| 路径 | 方法 | 认证 | 说明 |
|---|---|---|---|
| `/` | GET | ✅ | 管理面板 |
| `/login` | GET/POST | ❌ | 登录页 |
| `/logout` | GET | ✅ | 退出登录 |
| `/status` | GET | ✅ | JSON 状态 |
| `/login.png` | GET | ✅ | 二维码图片 |
| `/start` | POST | ✅ | 触发阅读 |
| `/restart` | POST | ✅ | 重启阅读（刷新二维码） |
| `/logs` | GET | ✅ | 查看日志 |
| `/healthz` | GET | ❌ | 健康检查 |
| `/api/notification` | GET/POST | ✅ | 查询或保存通知配置，支持仅更新指定渠道 |
| `/api/notification/test` | POST | ✅ | 按已保存的配置发送指定渠道的测试通知；JSON `channel` 可为 `webhook`、`bark`、`email`，默认飞书 |

## 本地运行

```bash
docker build -t weread-challenge .
docker run -d \
  --name weread-challenge \
  --restart unless-stopped \
  -p 8860:7860 \
  -v weread-data:/data \
  -e WEB_PASSWORD=your_password \
  weread-challenge
```

访问 `http://localhost:8860`，输入密码登录后扫码。

已有同名容器时，可以运行 `python3 scripts/redeploy.py --apply`。脚本先构建并验证新镜像，再保留原数据卷和启动参数替换容器，验证成功后移除原镜像。通过 `--webhook-from-stdin` 可从标准输入读取飞书配置的 JSON 对象；地址与密钥仅保存在运行数据卷中。脚本不会删除数据卷或清理其他服务镜像。
