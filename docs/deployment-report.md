# Deployment execution report

- Completed (UTC): 2026-10-21T06:15:43.963668+00:00
- Container: `weread-challenge`
- Image: `weread-challenge:latest`
- Image ID: `sha256:afd75293c2072fcab2df3d3e71638caed75177ded6c6dc6ffa5e5a72056aa2f2`
- Published port: `8860:7860`
- Container health: `healthy`
- Existing persistent data mount, environment and restart policy preserved.
- Previous service image reference removed; no data volumes or other services removed.
- Built-image verification: 27 tests passed; login, authenticated status and static assets passed HTTP checks.
- Feishu test: 飞书通知已发送
- Webhook credentials saved only to the runtime data volume; none written to this repository.
- Build used the current working tree, including pre-existing local Dockerfile and app.py changes. Those existing changes remain uncommitted.
- Dockerfile SHA-256: `74921d0f78795c98ad0ae83555c10088daad995ad3634af9a08136414a70904d`
- app.py SHA-256: `9a1836fb6e4f8135bc462fd9643883351da38f7140d59e32fb8f5cc201abf546`
