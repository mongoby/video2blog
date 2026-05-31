# video2blog 部署方案

> 基于 Docker Compose 的本地/内网部署

## 前提条件

- Docker Engine 24+（含 docker compose 插件）
- NVIDIA GPU + nvidia-container-toolkit（可选，用于 GPU 加速转写）
- 4GB+ 可用内存，5GB+ 磁盘空间

## 架构

```
┌─────────────┐     ┌──────────────┐     ┌───────────┐
│  Nginx      │────▶│  Flask API   │────▶│  JSON     │
│  (反向代理) │     │  (app.py)    │     │  文件存储  │
└─────────────┘     └──────────────┘     └───────────┘
       │                     │
       │              ┌──────┴──────┐
       │              │ faster-     │
       │              │ whisper     │
       │              │ (GPU/CPU)   │
       │              └─────────────┘
       ▼
┌──────────────┐
│  Vite SPA    │
│  (端口3000)  │
└──────────────┘
```

## 配置清单

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `FLASK_DEBUG` | `0` | 生产环境必须关闭 |
| `CORS_ORIGINS` | `*` | 限制前端域名，本地部署可保留 |
| `UPLOAD_MAX_SIZE` | `1048576000` | 上传文件上限（1GB） |
| `JOB_DIR` | `./jobs` | 任务数据存储目录 |

## 部署方式对比

### 方式一：Docker Compose（推荐）

```bash
# 构建并启动
docker compose up -d --build

# 查看日志
docker compose logs -f

# 更新
git pull && docker compose up -d --build

# 停止
docker compose down
```

### 方式二：本地直接运行

```bash
# 安装依赖
cd backend && pip3 install -r requirements.txt
cd frontend && npm install

# 启动（两个终端）
cd backend && python3 app.py              # :5000
cd frontend && npm run dev                 # :3000
```

### 方式三：systemd 服务（生产环境）

```ini
[Unit]
Description=video2blog backend
After=network.target

[Service]
Type=simple
User=z
WorkingDirectory=/mnt/d/video2blog/backend
ExecStart=/usr/bin/python3 app.py
Restart=always
RestartSec=5
Environment=FLASK_DEBUG=0

[Install]
WantedBy=multi-user.target
```

## 安全注意事项

1. **关闭 debug 模式**：`FLASK_DEBUG=0` 环境变量
2. **限制文件上传**：前端 + 后端双重检查文件大小
3. **CORS 限制**：生产环境设置具体域名而非 `*`
4. **使用 HTTPS**：Nginx 配置 SSL 证书

## 资源估算

| 组件 | CPU | 内存 | GPU 显存 |
|------|-----|------|----------|
| Flask API | 0.5 core | 256MB | - |
| Vite SPA (Nginx) | 0.1 core | 64MB | - |
| faster-whisper (base) | 2 cores | 1GB | 1GB |
| faster-whisper (large) | 4 cores | 2GB | 4GB |

## 监控建议

```bash
# 健康检查
curl http://localhost:5000/api/jobs | head

# 资源监控
docker stats

# 日志检查
docker compose logs --tail=50
```
