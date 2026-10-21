---
license: mit
sdk: docker
app_port: 7860
---

<p align="center"><img src="static/weread.jpg" width="72" height="72" alt="微信读书图标"></p>
<h1 align="center">weread-challenge</h1>
<p align="center">微信读书自动阅读与管理面板 · Docker 单容器部署</p>

基于 [weread-challenge-selenium](https://github.com/jqknono/weread-challenge-selenium) 和 [weread-challenge-hf](https://github.com/buyi06/weread-challenge-hf) 改造，使用固定版本的 `weread-selenium-cli@0.18.0`，将 Chromium、Xvfb、定时调度和 Flask 面板放在一个容器中。

## 功能

- 自动阅读，默认每次 68 分钟，每 12 小时检查并启动一次；容器启动后也会自动运行一次。
- 密码登录，管理阅读状态、扫码登录、手动启动和重新登录。
- 默认浅色，可切换深色并记住选择，适配桌面与手机。
- 阅读参数提供中文名称、单位和用途说明，技术参数折叠展示。
- Bark、邮件、飞书通知支持在面板中配置、启停和发送测试消息，首页只展示已有配置的渠道。
- 飞书在需要重新扫码时提醒，支持签名校验、持久化去重和失败重试。
- 摘要日志支持搜索、级别筛选、合并重复记录和暂停跟随，保留原始日志入口。
- 面板时间统一按北京时间（`Asia/Shanghai`，UTC+8）显示，悬停日志时间可查看完整日期。
- 登录信息、通知配置和运行记录保存在独立数据卷中。

## 快速开始

需要安装 Docker；默认将宿主机 **8860** 端口映射到容器的 **7860** 端口。

```bash
git clone https://github.com/jiang-yw/weread-challenge.git
cd weread-challenge
cp .env.example .env
```

编辑 `.env`，替换 `WEB_PASSWORD` 和 `SECRET_KEY`。它们分别是面板登录密码和登录会话签名密钥，应使用不同的随机值。可分别使用以下命令生成：

```bash
openssl rand -base64 24
openssl rand -hex 32
```

构建并启动：

```bash
docker build -t weread-challenge .
docker run -d \
  --name weread-challenge \
  --restart unless-stopped \
  -p 8860:7860 \
  -v weread-data:/data \
  --env-file .env \
  weread-challenge
```

访问 [http://localhost:8860](http://localhost:8860)，远程服务器则使用服务器地址的 `8860` 端口。输入 `.env` 中的面板密码后，用微信读书扫描登录二维码。浏览器保留登录会话时不会重复询问密码，点击「退出」或使用无痕窗口可验证登录限制。

应用数据保存在 `weread-data` 卷内的 `/data/.weread`。重建容器时继续挂载该卷即可保留登录和通知配置。`.env`、本地备份和运行数据已加入 Git 忽略规则。

## 通知管理

在面板点击「管理通知」，选择渠道，填写参数并保存。可先点击「测试已保存配置」确认送达，再启用渠道。保存配置本身不会发送测试消息。

| 渠道 | 需要填写 | 通知内容 | 配置生效时间 |
|---|---|---|---|
| 飞书 | 群机器人 Webhook；按需填写签名密钥、面板地址 | 需要重新扫码登录时提醒 | 后续登录事件 |
| Bark | 设备推送密钥；可选自建服务器 | 阅读程序的登录、任务启动、完成和异常通知 | 下一次阅读任务 |
| 邮件 | SMTP 服务器、端口、账号、授权码、收件人 | 扫码登录链接及阅读任务报告 | 下一次阅读任务 |

邮件常用端口为 `465`（SSL）或 `587`（STARTTLS）。授权码通常是邮箱开启 SMTP 后生成的应用授权码。

### 飞书登录提醒

1. 在飞书群中添加「自定义机器人」，复制其 Webhook 地址。
2. 如果开启关键词校验，将关键词设为 `微信读书`；开启签名校验时，同时复制签名密钥。详见[飞书官方说明](https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot)。
3. 在面板中填入 Webhook 和可选的签名密钥。管理面板地址应填写手机可以访问的地址，方便从通知中跳转。
4. 保存后发送测试通知，确认群里收到 `微信读书：飞书通知测试`。

提醒由阅读任务实际发现「需要登录」触发，包括首次未登录和 Cookie 失效。默认任务间隔为 12 小时，因此通常要等到下一次任务才能发现失效，并非到期瞬间检测。

同一次登录失效成功通知后，二维码刷新、后续任务和容器重启不会重复提醒；检测到登录成功后解除去重。失败的发送不会阻断阅读，同一次任务的后续登录事件可重试，两次尝试至少间隔 60 秒。测试通知不影响去重状态。

### 配置优先级

地址、账号和密钥优先使用容器环境变量，面板会标明并锁定这些字段；未通过环境变量设置的字段使用面板保存的值。**启用开关由面板单独控制**，可以停用渠道并保留凭据。

面板保存的通知配置写入数据卷中的 `notification_config.json`。密钥和飞书 Webhook 在接口中隐藏为 `***set***`，保留这个值表示不修改。

## 环境变量

### 登录与阅读

| 变量 | 默认值 | 说明 |
|---|---|---|
| `WEB_PASSWORD` | `linuxdo123`，部署时请覆盖 | 面板登录密码 |
| `SECRET_KEY` | 代码保留兼容值，部署时请覆盖 | Flask 会话签名密钥；更换后旧登录会话失效 |
| `WEREAD_DURATION` | `68` | 每次阅读时长，单位分钟 |
| `READING_INTERVAL_HOURS` | `12` | 自动检查并启动任务的间隔，单位小时 |
| `WEREAD_SPEED` | `slow` | 翻页速度：`slow`、`normal`、`fast` |
| `WEREAD_SELECTION` | `2` | 正整数表示书架第几本；`0` 随机选择前四本；`-1` 使用指定链接 |
| `DEFAULT_BOOK_URL` | 阅读程序内置链接 | 指定链接模式，或无法从书架选书时使用的链接 |
| `WEREAD_SCREENSHOT` | `true` | 阅读过程中按分钟保存截图 |
| `SCREENSHOT_KEEP` | `10` | 保留最近的阅读截图数量 |
| `WEREAD_AGREE_TERMS` | `true` | 控制向上游项目统计服务提交运行和微信读书用户信息；设为 `false` 可关闭 |
| `WEREAD_DATA_DIR` | `/data/.weread` | 容器内数据目录 |

阅读参数在面板中展示；修改容器环境变量后，需要重新创建容器。当前 Cookie 的保存时间仅供参考，是否需要重新登录由实际阅读任务判断。过期二维码不会继续展示。

### 通知

| 渠道 | 变量 | 说明 |
|---|---|---|
| 飞书 | `WEBHOOK_URL` | 群自定义机器人的 Webhook 地址 |
| 飞书 | `WEBHOOK_SECRET` | 可选，机器人签名校验密钥 |
| 飞书 | `WEREAD_PANEL_URL` | 可选，通知中的管理面板链接 |
| Bark | `BARK_KEY` | 设备推送密钥 |
| Bark | `BARK_SERVER` | 服务器地址，默认 `https://api.day.app` |
| 邮件 | `ENABLE_EMAIL` | 初始启用状态，`true` 或 `false`；面板开关优先 |
| 邮件 | `EMAIL_SMTP`、`EMAIL_PORT` | SMTP 地址和端口，端口默认 `465` |
| 邮件 | `EMAIL_USER`、`EMAIL_PASS` | 登录账号和 SMTP 授权码 |
| 邮件 | `EMAIL_TO` | 收件人邮箱 |
| 邮件 | `EMAIL_FROM` | 可选，留空时使用 `EMAIL_USER` |

上述通知字段也可直接在面板配置。未设置 `ENABLE_EMAIL` 时，完整的邮件配置会作为默认启用状态；已有面板开关则以保存的开关为准。

## 更新部署

在已有同名容器的项目目录中运行：

```bash
git pull --ff-only
python3 scripts/redeploy.py --apply
```

脚本会构建新镜像并运行测试，复用原数据卷、端口、环境变量和重启策略，再替换容器并检查健康状态；替换验证失败时尝试恢复原镜像。服务启动会自动触发一次阅读，正在运行的旧任务会随容器替换结束。

该脚本复用旧容器的环境变量，不会重新读取 `.env`。需要修改环境变量时，停止并移除旧容器，再按「快速开始」中的 `docker run` 命令重新创建。保留 `weread-data` 卷即可保留数据。

构建默认使用腾讯云 Debian/npm 镜像源。`DEBIAN_MIRROR_HTTP`、`DEBIAN_SECURITY_MIRROR_HTTP`、`DEBIAN_MIRROR_HTTPS`、`DEBIAN_SECURITY_MIRROR_HTTPS` 和 `NPM_REGISTRY` 支持通过 `docker build --build-arg` 覆盖。

## Hugging Face Spaces

项目保留 Docker SDK 的配置，容器端口为 `7860`。同步完整仓库文件，在 Space Secrets 中设置独立的 `WEB_PASSWORD` 和 `SECRET_KEY`，将持久化存储挂载到 `/data`。

默认登录 Cookie 使用 `SameSite=Lax`，适合直接打开服务地址。跨站 iframe 中登录可能受 Cookie 策略限制，可在新标签页直接打开 Space 的服务地址。项目提供 `/healthz` 健康检查，当前代码没有自动自 ping 功能。

## 日志与时间

摘要日志只读取最近 256 KB，过滤重复按键、截图大小、未配置渠道提示和上游统计详细数据，保留关键事件及异常。关闭「跟随新日志」后，刷新会保留滚动位置；排查完整上下文可打开「原始日志」。

面板的日志、任务开始与结束时间统一按北京时间显示。未标明时区的旧阅读日志按 UTC 解析，带时区偏移的时间戳按实际时刻转换，避免重复加 8 小时。原始日志文件保持原样。

## 验证

使用已有镜像运行单元测试，不挂载真实数据卷：

```bash
docker run --rm --network none --read-only \
  --entrypoint python3 \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e SCRATCH_ROOT=/dev/shm -e TMPDIR=/dev/shm \
  -e WEREAD_DATA_DIR=/dev/shm/weread-tests \
  --mount type=bind,source="$PWD/tests",target=/qa/tests,readonly \
  weread-challenge -m unittest discover -s /qa/tests -v
```

浏览器检查覆盖主题、通知配置、日志筛选、北京时间转换、跨日和手机布局：

```bash
docker run --rm --network none --read-only --shm-size 512m \
  --entrypoint python3 \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e SCRATCH_ROOT=/dev/shm -e TMPDIR=/dev/shm \
  -e WEREAD_QA_DIR=/dev/shm/weread-qa \
  --mount type=bind,source="$PWD",target=/app,readonly \
  weread-challenge tests/run_browser_checks.py
```

检查使用临时登录数据、本地模拟 HTTP 服务和模拟通知，不启动阅读任务、不使用真实 Cookie、不向外部发送通知。浏览器截图保存在容器的 `WEREAD_QA_DIR`；如需保留，可将该目录挂载到宿主机的临时目录。

## 接口

除登录页、静态资源和健康检查外，接口均需要面板登录会话。

| 路径 | 方法 | 用途 |
|---|---|---|
| `/` | GET | 管理面板 |
| `/login` | GET / POST | 密码登录 |
| `/logout` | GET | 退出登录 |
| `/status` | GET | 阅读状态、配置摘要和通知状态 |
| `/login.png` | GET | 当前登录二维码 |
| `/start` | POST | 手动启动阅读 |
| `/restart` | POST | 结束当前阅读、清除登录信息并重新扫码 |
| `/stop` | POST | 结束当前阅读任务 |
| `/logs` | GET | 原始日志尾部 |
| `/logs/clean` | GET | 筛选后的摘要日志 |
| `/api/notification` | GET / POST | 查询或保存通知配置 |
| `/api/notification/test` | POST | 测试渠道：JSON `channel` 为 `webhook`、`bark` 或 `email`，默认飞书 |
| `/healthz` | GET | 无需登录的健康检查 |

通知触发依赖固定 CLI 版本的登录日志格式。升级 `WEREAD_CLI_VERSION` 时，应核对事件格式并重新运行测试。
