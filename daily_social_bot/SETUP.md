# Daily Social Automation — 部署指南

## 流程图

```
每天 09:00
    ↓
抓取 X + 小红书
    ↓
Claude 选最佳内容
    ↓
Claude 生成 3 条推文草稿
    ↓
发送到企业微信（应用消息）
    ↓
你回复 1 / 2 / 3
    ↓
自动发布到 X
```

---

## 一、前置准备

### 1. Twitter API v2
1. 申请 [Twitter Developer Portal](https://developer.twitter.com/) 项目
2. 需要 **Elevated** 权限（免费 Basic 仅能读）
3. 在 User Authentication Settings 开启 **Read and Write**
4. 获取：API Key / API Secret / Access Token / Access Token Secret / Bearer Token

### 2. 小红书 Cookie
1. Chrome 登录 www.xiaohongshu.com
2. DevTools → Application → Cookies → 复制完整 Cookie 字符串
3. **注意**：小红书 API 需要签名（`x-s` / `x-t`），
   默认实现留空会返回 471 错误。
   可集成 [xhs 签名库](https://github.com/ReaJason/xhs) 补全签名逻辑
   （修改 `fetchers/xhs_fetcher.py` 的 `_sign_request` 方法）

### 3. Claude API Key
- 前往 [console.anthropic.com](https://console.anthropic.com/) 获取

### 4. 企业微信应用
1. 企业微信管理后台 → 应用管理 → 自建应用 → 创建
2. 记录：CorpID / AgentID / Secret
3. 在应用 **接收消息** 设置中填写：
   - URL：`https://your-server.com/wecom/callback`
   - Token：自定义随机字符串
   - EncodingAESKey：随机生成
4. 确认可达性后保存

---

## 二、配置

```bash
cd daily_social_bot
cp .env.example .env
# 填写 .env 中所有变量
```

修改 `config.yaml`：
- `sources.twitter.accounts`：你想关注的账号
- `sources.xiaohongshu.keywords`：搜索关键词
- `generator.style`：你的推文风格示例（越具体越好）
- `selector.criteria`：筛选偏好

---

## 三、运行

### 本地测试（立即执行一次）

```bash
pip install -r requirements.txt
python main.py --run-now
```

### Docker 部署

```bash
docker build -t daily-social-bot .
docker run -d \
  --env-file .env \
  -p 8080:8080 \
  --restart unless-stopped \
  daily-social-bot
```

### 公网回调
企业微信回调需要公网地址。本地开发可用：
```bash
# 安装 cloudflared 或 ngrok
cloudflared tunnel --url http://localhost:8080
# 把生成的 URL 填到 .env 的 CALLBACK_URL 和企业微信后台
```

---

## 四、使用

每天 09:00 自动运行。你会收到企业微信消息：

```
📰 今日素材：@karpathy
🔗 https://x.com/...

── 请回复数字选择要发布的推文 ──

[1]
大模型正在把搜索引擎变成答案机器。...

[2]
...

[3]
...

── 操作 ──
回复 1 / 2 / 3  →  发布对应推文
回复 0          →  今日跳过
```

回复数字后，推文自动发布，并收到确认消息。

---

## 五、自定义风格

在 `config.yaml` 的 `generator.style` 中贴入 3-5 条你自己写的推文示例，
AI 会学习你的用词、句式和长度习惯。示例越真实，效果越好。
