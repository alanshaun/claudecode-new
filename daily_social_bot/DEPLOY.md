# 部署指南（GitHub Actions + Render 免费方案）

## 架构

```
每天 09:00 (北京时间)
    ↓
GitHub Actions 自动运行
    ↓ 抓取 X + 小红书
    ↓ Kimi 筛选 + 生成3条推文
    ↓
发送飞书交互卡片（推文内容嵌入按钮）
    ↓
你点击按钮
    ↓
Render 收到回调 → 发布到 X → 飞书通知结果
```

---

## 第一步：部署 Render（接收飞书按钮回调）

1. 打开 render.com → 用 GitHub 登录
2. New → Web Service → 连接 `alanshaun/claudecode-new`
3. 设置：
   - **Root Directory**: `daily_social_bot`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn server.callback:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: Free
4. 添加环境变量（Environment → Add Environment Variable）：

| Key | Value |
|-----|-------|
| TWITTER_API_KEY | IdVtgYUzjydcasas8H2popo4u |
| TWITTER_API_SECRET | 5EySpEn1CpMhJtwqs1gEJyuP6snTSlKGqLXFeTiGV1nLcySUdh |
| TWITTER_ACCESS_TOKEN | 1826688783070248962-IVs3GMO3sV4Qg3lExWedLlWU12UAAB |
| TWITTER_ACCESS_TOKEN_SECRET | KIRQGD2XTCCLOgI3eMa5REONjDbViiUdVeVHH7IHNnM5d |
| FEISHU_APP_ID | cli_a9493909c1611cc6 |
| FEISHU_APP_SECRET | 2oWswLgRJLSQGerzCOEXkeJBy35ShOGL |
| FEISHU_USER_ID | ou_0d87b97dab5ad3be9fceefa57b2a8aff |

5. 点 Deploy → 等待完成，记录域名如 `https://daily-social-bot-xxxx.onrender.com`

---

## 第二步：配置飞书回调地址

1. 打开 open.feishu.cn → 你的应用 → **事件订阅**
2. 请求地址填：`https://daily-social-bot-xxxx.onrender.com/feishu/callback`
3. 保存并验证

---

## 第三步：添加 GitHub Actions Secrets

打开 github.com → 你的仓库 → Settings → Secrets and variables → Actions → New repository secret

逐一添加：

| Secret 名称 | 值 |
|------------|-----|
| TWITTER_API_KEY | IdVtgYUzjydcasas8H2popo4u |
| TWITTER_API_SECRET | 5EySpEn1CpMhJtwqs1gEJyuP6snTSlKGqLXFeTiGV1nLcySUdh |
| TWITTER_ACCESS_TOKEN | 1826688783070248962-IVs3GMO3sV4Qg3lExWedLlWU12UAAB |
| TWITTER_ACCESS_TOKEN_SECRET | KIRQGD2XTCCLOgI3eMa5REONjDbViiUdVeVHH7IHNnM5d |
| TWITTER_BEARER_TOKEN | AAAAAAAAAAAAAAAAAAAAAEcE8gEAAAAAeV1PHP%2FHAdApDCx9o3d0gs5KZ6E%3DjYduXSSNGK38znnkioMpzO5zLQt9GB51DBFpCXwX4g6U0Yqt1X |
| KIMI_API_KEY | sk-m9kVL52fZbRu4PjH9yj2JJ1ruKDUDjaJzvuD8qcXBd3EOvrG |
| GEMINI_API_KEY | AIzaSyD2TGnFz8G3Hj1DcA2Yi71NhZAZP3fu8U4 |
| XHS_COOKIE | （见 .env 文件中的完整 cookie 字符串） |
| FEISHU_APP_ID | cli_a9493909c1611cc6 |
| FEISHU_APP_SECRET | 2oWswLgRJLSQGerzCOEXkeJBy35ShOGL |
| FEISHU_USER_ID | ou_0d87b97dab5ad3be9fceefa57b2a8aff |
| RENDER_POST_URL | https://daily-social-bot-xxxx.onrender.com/feishu/callback |
| POST_SECRET | （随机字符串，自定义即可） |

---

## 第四步：手动测试

GitHub → Actions → Daily Social Automation → Run workflow → 点 Run

正常的话飞书会收到一张卡片，点按钮即可发推。
