# 🎬 video2blog

AI 短视频转博客工具。粘贴链接或上传视频 → faster-whisper GPU 转录 → DeepSeek AI 生成博客 → 在线编辑 → 导出 Markdown。

**技术栈**: React + Ant Design 5 (前端) · Flask 3 (后端) · faster-whisper (转录) · DeepSeek API (生成)

---

## 功能

| 步骤 | 说明 |
|------|------|
| 🎬 输入 | 拖拽上传视频，或粘贴抖音/B站/YouTube/小红书等平台链接 |
| 🤖 转录 | faster-whisper GPU 加速（支持 tiny / base / small / medium / large-v3） |
| ✍️ 生成 | DeepSeek AI 生成结构化博客（4 种语气 × 多档长度） |
| 📝 编辑 | 内置 Markdown 预览编辑器 |
| 📤 导出 | 一键下载 Markdown 文件 |

## 快速开始

### 1. 后端

```bash
cd backend

# 安装依赖（GPU 版需要 torch CUDA）
pip3 install -r requirements.txt

# 配置 API Key
cp .env.example .env
# 编辑 .env，填入 DeepSeek API Key
```

推荐使用 **DeepSeek**（国内直连），去 [platform.deepseek.com](https://platform.deepseek.com) 注册获取。

也支持 OpenAI 兼容接口，修改 `.env` 中的 `DEEPSEEK_BASE_URL` 和 `DEEPSEEK_API_KEY` 即可。

### 2. 启动后端

```bash
cd backend
python3 app.py
# → http://localhost:5000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

### 4. 访问

浏览器打开 **http://localhost:3000**

## Docker 部署

```bash
docker compose up -d --build
```

前端 :3000，后端 :5000，Nginx 统一入口 :80。


## 技术细节

- **转录**: faster-whisper 1.x（CUDA GPU / CPU 两用）
- **AI**: DeepSeek V4 Flash / V4 Pro（OpenAI 兼容接口）
- **前端**: React 18 + Ant Design 5 + Vite 6
- **后端**: Flask 3 + flask-cors
- **样式**: Notion 风格浅色主题
- **视频下载**: yt-dlp → you-get → Playwright 三阶自动降级

## License

MIT
