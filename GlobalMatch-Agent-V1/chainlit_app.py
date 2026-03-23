"""
GlobalMatch-Agent-V1 Chainlit主界面
全简体中文，傻瓜操作
支持：自然语言输入、PDF上传、进度实时更新、买家列表展示、批量发送、历史记录
"""
import sys
from pathlib import Path

# 确保项目根目录在 Python 路径中（Chainlit 可能从其他目录加载）
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import asyncio
import hashlib
import os
import uuid
import structlog
from datetime import datetime, timezone
from typing import Optional

import chainlit as cl
from chainlit.input_widget import Select, Slider, TextInput, Switch

from config import settings
from database.supabase_client import db
from tasks.search_task import run_search  # 顶层导入，避免 on_chat_start 中 No module named 'tasks'
from database.supabase_client import (
    TABLE_SEARCH_TASKS, TABLE_SEARCH_RESULTS,
    TABLE_SENT_EMAILS, TABLE_REPLIES, TABLE_NOTIFICATIONS,
    TABLE_USER_SETTINGS
)
from agent.kimi_client import kimi_client
from utils.pdf_parser import pdf_parser
from utils.wechat_notify import wechat_notifier

logger = structlog.get_logger(__name__)

# ---- 配置structlog ----
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
)


# ==============================================================================
# Chainlit 生命周期
# ==============================================================================

@cl.on_chat_start
async def on_chat_start():
    """初始化会话"""
    # 欢迎消息
    await cl.Message(
        content="""# 🌍 GlobalMatch-Agent-V1 欢迎使用！

**你的AI全球买家开发助手**

我可以帮你：
- 🔍 **搜索全球买家**：输入你的产品描述，我自动从20个全球数据源爬取真实买家
- 📧 **一键发送开发信**：AI生成个性化英文邮件，用你的邮箱批量发送
- 📱 **微信回复提醒**：买家回复时，立即推送微信通知
- 📊 **全程存档**：搜索、发送、回复全部记录

---

**开始使用，请告诉我你的产品（中文英文都可以）：**

例如：
- "我们做LED工矿灯，想找美国和德国的工业照明进口商"
- "太阳能充电宝，目标东南亚和中东批发商"
- "不锈钢餐具，找欧洲超市采购商"

💡 **小技巧**：你还可以上传产品PDF或输入产品页面链接，我会自动提取产品信息！

输入 `/设置` 配置邮箱和微信通知
输入 `/历史` 查看历史记录
输入 `/帮助` 查看所有命令
""",
        author="GlobalMatch助手"
    ).send()

    # 初始化会话状态
    cl.user_session.set("state", "waiting_for_product")
    cl.user_session.set("current_task_id", None)
    cl.user_session.set("current_buyers", [])
    cl.user_session.set("product_info", {})
    cl.user_session.set("search_params", {})

    # 检查是否有未完成的任务（用户重新打开页面后自动恢复）
    try:
        running_tasks = await db.select(
            TABLE_SEARCH_TASKS,
            {"status": "running"},
            limit=1,
            order_by="created_at",
            order_desc=True
        )
        if not running_tasks:
            running_tasks = await db.select(
                TABLE_SEARCH_TASKS,
                {"status": "pending"},
                limit=1,
                order_by="created_at",
                order_desc=True
            )
        if running_tasks:
            task = running_tasks[0]
            task_id = task.get("task_id")
            status = task.get("status", "pending")
            user_query = task.get("user_query", "")
            target_count = task.get("target_count", 100)
            cl.user_session.set("current_task_id", task_id)
            cl.user_session.set("state", "searching")

            # pending 任务可能是之前 Celery 未收到的孤儿任务，立即重新提交
            if status == "pending":
                try:
                    run_search.apply_async(
                        args=[task_id, user_query, target_count, None, None],
                        queue="search",
                    )
                    logger.info("恢复：pending 任务已重新提交 Celery", task_id=task_id)
                    await cl.Message(
                        content="""🔄 **发现未启动的搜索，已重新提交 Worker** · 进度见右上角"""
                    ).send()
                except Exception as e:
                    logger.error("重新提交任务失败", task_id=task_id, error=str(e))
                    await cl.Message(
                        content=f"""🔄 **发现未完成的搜索**，但重新提交失败：{e}\n请重新输入产品描述开始新搜索"""
                    ).send()
                    cl.user_session.set("state", "waiting_for_product")
                    return
            else:
                await cl.Message(
                    content="""🔄 **检测到未完成的搜索，自动恢复监控** · 进度见右上角"""
                ).send()
            asyncio.create_task(poll_task_progress(task_id))
    except Exception as e:
        logger.warning("检查历史任务失败", error=str(e))


@cl.on_message
async def on_message(message: cl.Message):
    """处理用户消息"""
    content = message.content.strip()
    state = cl.user_session.get("state", "waiting_for_product")

    # ---- 命令路由 ----
    if content.startswith("/"):
        await handle_command(content, message)
        return

    # ---- 状态路由 ----
    if state == "waiting_for_product":
        await handle_product_input(message)
    elif state == "waiting_for_count":
        await handle_count_selection(content)
    elif state == "searching":
        await handle_searching_state(content)
    elif state == "waiting_for_channel":
        await handle_channel_selection(content)
    elif state == "settings":
        await handle_settings_input(content)
    else:
        # 未知状态，重置并重新开始
        cl.user_session.set("state", "waiting_for_product")
        await handle_product_input(message)


# ==============================================================================
# 命令处理
# ==============================================================================

async def handle_command(content: str, message: cl.Message):
    """处理斜杠命令"""
    cmd = content.lower().split()[0]

    if cmd in ("/设置", "/settings"):
        await show_settings()
    elif cmd in ("/历史", "/history"):
        await show_history()
    elif cmd in ("/帮助", "/help"):
        await show_help()
    elif cmd in ("/状态", "/status"):
        await show_current_status()
    elif cmd in ("/取消", "/cancel"):
        await cancel_current_task()
    else:
        await cl.Message(content=f"未知命令：`{cmd}`，输入 `/帮助` 查看所有命令").send()


# ==============================================================================
# 产品输入处理
# ==============================================================================

async def handle_product_input(message: cl.Message):
    """处理产品描述输入"""
    user_query = message.content.strip()
    pdf_path = None
    link_url = None

    # 处理上传文件
    if message.elements:
        for element in message.elements:
            if hasattr(element, 'path') and element.path:
                if element.name.lower().endswith(".pdf"):
                    pdf_path = element.path
                    await cl.Message(content=f"📄 已收到PDF文件：**{element.name}**，正在解析...").send()
                    break

    # 检测URL
    import re
    urls = re.findall(r'https?://[^\s]+', user_query)
    if urls:
        link_url = urls[0]
        user_query = re.sub(r'https?://[^\s]+', '', user_query).strip()

    if not user_query and not pdf_path and not link_url:
        await cl.Message(content="请输入你的产品描述，例如：'LED工矿灯，找美国进口商'").send()
        return

    # 保存到会话
    cl.user_session.set("user_query", user_query)
    cl.user_session.set("pdf_path", pdf_path)
    cl.user_session.set("link_url", link_url)

    # 提取产品信息
    thinking_msg = cl.Message(content="🤔 AI正在分析你的产品信息...")
    await thinking_msg.send()

    product_context = ""
    if pdf_path:
        pdf_result = pdf_parser.parse(pdf_path)
        if not pdf_result.get("error"):
            product_context = (
                f"产品名: {pdf_result.get('product_name', '')}\n"
                f"规格: {', '.join(pdf_result.get('specs', [])[:5])}\n"
                f"卖点: {', '.join(pdf_result.get('selling_points', [])[:5])}"
            )
            await cl.Message(
                content=f"✅ PDF解析完成！\n产品名：**{pdf_result.get('product_name', '未识别')}**"
            ).send()

    if link_url:
        await cl.Message(content=f"🔗 正在抓取链接：{link_url}...").send()
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(link_url, follow_redirects=True)
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for tag in soup(["script", "style", "nav", "footer"]):
                        tag.decompose()
                    page_text = soup.get_text(separator=" ", strip=True)[:2000]
                    product_context += f"\n链接内容: {page_text}"
                    await cl.Message(content="✅ 链接内容已提取").send()
        except Exception as e:
            await cl.Message(content=f"⚠️ 链接抓取失败：{e}，将使用文字描述继续").send()

    # Kimi分析
    search_params = await kimi_client.analyze_product_query(user_query, product_context)
    cl.user_session.set("search_params", search_params)

    product_info = {
        "product_name": search_params.get("product_summary", user_query),
        "industry": search_params.get("industry", ""),
        "keywords": search_params.get("keywords_en", []),
        "selling_points": [],
        "specs": [],
    }
    if pdf_path:
        pdf_result = pdf_parser.parse(pdf_path)
        product_info["selling_points"] = pdf_result.get("selling_points", [])
        product_info["specs"] = pdf_result.get("specs", [])

    cl.user_session.set("product_info", product_info)

    # 展示分析结果
    keywords = search_params.get("keywords_en", [])
    countries = search_params.get("target_countries", [])
    buyer_types = search_params.get("buyer_types", [])

    await cl.Message(
        content=f"""✅ **产品分析完成！**

📦 **产品摘要**：{search_params.get('product_summary', user_query)}
🔑 **搜索关键词**：{', '.join(keywords)}
🌍 **目标国家**：{', '.join(countries[:8])}
👥 **买家类型**：{', '.join(buyer_types)}

---
**请选择要搜索的买家数量：**
- 输入 `100` - 搜索100家（推荐，约5-10分钟）
- 输入 `200` - 搜索200家（约10-20分钟）
- 输入 `300` - 搜索300家（约20-30分钟）
"""
    ).send()

    cl.user_session.set("state", "waiting_for_count")


# ==============================================================================
# 搜索进行中的处理
# ==============================================================================

async def handle_searching_state(content: str):
    """搜索进行中，处理用户输入"""
    task_id = cl.user_session.get("current_task_id")

    # 允许 /状态 类命令（已在上层命令路由处理，这里只处理普通文本）
    if content.strip() in ("取消", "cancel", "/取消"):
        await cancel_current_task()
        return

    # 查询当前进度
    status_text = "进行中"
    progress = 0
    if task_id:
        try:
            records = await db.select(TABLE_SEARCH_TASKS, {"task_id": task_id}, limit=1)
            if records:
                task = records[0]
                status = task.get("status", "running")
                progress = task.get("progress", 0)
                status_msg = task.get("status_message", "")
                result_count = task.get("result_count", 0)
                status_text = f"{progress}% | {status_msg}" if status_msg else f"{progress}%"
                if status == "completed":
                    await show_search_results(task_id, result_count)
                    return
        except Exception:
            pass

    filled = int(progress / 10)
    bar = "█" * filled + "░" * (10 - filled)
    await cl.Message(
        content=f"⏳ **搜索正在后台运行中，请耐心等待...**\n\n"
                f"进度：`[{bar}]` {progress}%\n"
                f"任务ID：`{task_id}`\n\n"
                f"💡 输入 `/状态` 刷新进度，输入 `取消` 中止任务\n"
                f"你也可以关闭浏览器，搜索仍会继续，完成后推送微信通知"
    ).send()


# ==============================================================================
# 数量选择
# ==============================================================================

async def handle_count_selection(content: str):
    """处理搜索数量选择"""
    count_map = {"100": 100, "200": 200, "300": 300}
    count = count_map.get(content.strip(), None)

    if not count:
        await cl.Message(content="请输入 `100`、`200` 或 `300`").send()
        return

    cl.user_session.set("target_count", count)
    await start_search_task(count)


# ==============================================================================
# 搜索任务启动
# ==============================================================================

async def start_search_task(target_count: int):
    """启动后台搜索任务"""
    task_id = f"task_{uuid.uuid4().hex[:12]}"
    user_query = cl.user_session.get("user_query", "")
    search_params = cl.user_session.get("search_params", {})
    pdf_path = cl.user_session.get("pdf_path")
    link_url = cl.user_session.get("link_url")

    cl.user_session.set("current_task_id", task_id)
    cl.user_session.set("state", "searching")

    # 创建任务记录
    query_hash = hashlib.md5(f"{user_query}{target_count}".encode()).hexdigest()[:12]
    await db.insert(TABLE_SEARCH_TASKS, {
        "task_id": task_id,
        "user_query": user_query,
        "keywords": search_params.get("keywords_en", []),
        "target_countries": search_params.get("target_countries", []),
        "buyer_types": search_params.get("buyer_types", []),
        "target_count": target_count,
        "status": "pending",
        "progress": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    # 简短提示，进度条在 poll_task_progress 中通过右上角浮动显示
    await cl.Message(
        content="""🚀 **搜索已启动**，进度见右上角 · 可关闭浏览器，任务继续运行"""
    ).send()

    # 提交Celery任务
    try:
        celery_task = run_search.apply_async(
            args=[task_id, user_query, target_count, pdf_path, link_url],
            queue="search"
        )
        cl.user_session.set("celery_task_id", celery_task.id)
        logger.info("Celery任务已提交", celery_id=celery_task.id)
        # 立即更新进度，让用户看到变化（失败不影响主流程）
        try:
            await db.update(TABLE_SEARCH_TASKS, {"task_id": task_id}, {
                "progress": 1,
                "status_message": "已提交 Worker，等待处理...",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        except Exception:
            pass
    except Exception as e:
        logger.error("Celery任务提交失败", error=str(e))
        await db.update(TABLE_SEARCH_TASKS, {"task_id": task_id}, {
            "status": "failed",
            "error_message": str(e)[:200],
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        await cl.Message(
            content=f"⚠️ 任务提交失败：{e}\n请检查 Redis 和 Celery Worker 是否运行：\n\n终端执行：\n`celery -A tasks.celery_app worker --loglevel=info -Q search`"
        ).send()
        return

    # 实时轮询进度（每5秒）
    await poll_task_progress(task_id)


async def poll_task_progress(task_id: str):
    """实时轮询任务进度，每5秒更新一次"""
    max_polls = 360  # 最多轮询30分钟（360 * 5s）
    progress_msg = None
    start_time = asyncio.get_event_loop().time()

    for i in range(max_polls):
        await asyncio.sleep(5)

        try:
            records = await db.select(TABLE_SEARCH_TASKS, {"task_id": task_id}, limit=1)
            if not records:
                continue

            task = records[0]
            status = task.get("status", "pending")
            progress = task.get("progress", 0)
            result_count = task.get("result_count", 0)
            status_message = task.get("status_message", "")

            # 若 pending 超过 2 分钟且进度为 0，可能 Worker 未收到，尝试重新提交
            elapsed = int(asyncio.get_event_loop().time() - start_time)
            if status == "pending" and progress <= 1 and elapsed >= 120:
                try:
                    run_search.apply_async(
                        args=[
                            task_id,
                            task.get("user_query", ""),
                            task.get("target_count", 100),
                            None, None  # pdf_path, link_url 会话中可能已丢失
                        ],
                        queue="search",
                    )
                    await db.update(TABLE_SEARCH_TASKS, {"task_id": task_id}, {
                        "status_message": "已重新提交 Worker，等待处理...",
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                    logger.info("pending 超时，已重新提交 Celery 任务", task_id=task_id)
                except Exception as e:
                    logger.warning("重新提交任务失败", task_id=task_id, error=str(e))
            elapsed_str = f"{elapsed // 60}分{elapsed % 60}秒" if elapsed >= 60 else f"{elapsed}秒"

            status_line = status_message if status_message else {
                "pending": "等待启动...",
                "running": "搜索中...",
                "completed": "完成",
                "failed": "失败",
                "timeout": "超时"
            }.get(status, status)

            result_line = f"已找到 {result_count} 家" if result_count > 0 else ""
            result_html = f'<div style="font-size:12px;color:var(--primary,#4CAF50);margin-top:4px">{result_line}</div>' if result_line else ""

            # 右上角浮动进度条（HTML + custom CSS 定位）
            progress_html = f'''<div id="msg-progress-float" class="msg-progress-float">
<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
<span style="font-size:14px">⏳</span>
<strong style="font-size:14px">搜索进度</strong>
<span style="margin-left:auto;font-size:12px;opacity:0.8">{elapsed_str}</span>
</div>
<div style="height:8px;background:rgba(0,0,0,0.1);border-radius:4px;overflow:hidden;margin-bottom:8px">
<div style="height:100%;width:{progress}%;background:linear-gradient(90deg,#4CAF50,#8BC34A);transition:width 0.3s;border-radius:4px"></div>
</div>
<div style="font-size:12px;opacity:0.9">{status_line} · <strong>{progress}%</strong></div>
{result_html}
<div style="font-size:11px;opacity:0.6;margin-top:6px">关闭页面后任务继续运行</div>
</div>'''

            if progress_msg is None:
                progress_msg = cl.Message(content=progress_html)
                await progress_msg.send()
            else:
                progress_msg.content = progress_html
                await progress_msg.update()

            if status == "completed":
                await show_search_results(task_id, result_count)
                return
            elif status == "failed":
                error = task.get("error_message", "未知错误")
                await cl.Message(
                    content=f"❌ **搜索失败**：{error}\n请重试或联系支持"
                ).send()
                cl.user_session.set("state", "waiting_for_product")
                return
            elif status == "timeout":
                await cl.Message(
                    content=f"⏰ **搜索超时**（30分钟限制），已获取部分结果"
                ).send()
                await show_search_results(task_id, result_count)
                return

        except Exception as e:
            logger.error("轮询进度失败", error=str(e))

    # 轮询超时
    await cl.Message(
        content="⚠️ 进度轮询超时，请输入 `/状态` 查看最新进度"
    ).send()


# ==============================================================================
# 展示搜索结果
# ==============================================================================

async def show_search_results(task_id: str, result_count: int):
    """展示搜索结果和买家列表"""
    # 获取买家数据
    buyers = await db.select(
        TABLE_SEARCH_RESULTS,
        {"task_id": task_id},
        limit=result_count,
        order_by="created_at",
        order_desc=False
    )

    if not buyers:
        await cl.Message(content="😔 未找到买家数据，请尝试更换关键词").send()
        cl.user_session.set("state", "waiting_for_product")
        return

    cl.user_session.set("current_buyers", buyers)
    cl.user_session.set("current_task_id", task_id)

    # 统计数据
    with_email = sum(1 for b in buyers if b.get("email"))
    with_website = sum(1 for b in buyers if b.get("website"))
    countries = list(set(b.get("country", "未知") for b in buyers if b.get("country")))[:10]

    # 展示统计
    await cl.Message(
        content=f"""🎉 **搜索完成！找到 {len(buyers)} 家潜在买家**

📊 **统计**：
- 有效邮箱：**{with_email}** 家
- 有官网：**{with_website}** 家
- 覆盖国家：{', '.join(countries[:8])}{'...' if len(countries) > 8 else ''}

---
**买家列表（前20家）：**
"""
    ).send()

    # 展示买家列表（每次展示20家）
    display_buyers = buyers[:20]
    buyer_list_text = ""
    for i, buyer in enumerate(display_buyers, 1):
        email_str = f"📧 {buyer.get('email', '无邮箱')}" if buyer.get('email') else "📧 无邮箱"
        website_str = f"🌐 {buyer.get('website', '')[:50]}" if buyer.get('website') else ""
        linkedin_str = f"💼 LinkedIn" if buyer.get('linkedin') else ""
        whatsapp_str = f"📱 WhatsApp" if buyer.get('whatsapp') else ""

        contact_icons = " | ".join(filter(None, [linkedin_str, whatsapp_str]))

        buyer_list_text += (
            f"{i}. **{buyer.get('company_name', '未知公司')}** [{buyer.get('country', '未知')}]\n"
            f"   {email_str} {website_str}\n"
            f"   {contact_icons}\n\n"
        )

    if len(buyers) > 20:
        buyer_list_text += f"...以及另外 **{len(buyers) - 20}** 家买家\n"

    await cl.Message(content=buyer_list_text).send()

    # 发送选项
    await cl.Message(
        content="""---
**请选择发送方式：**

- 输入 `全部邮件` - 给所有有邮箱的买家发邮件
- 输入 `全部WhatsApp` - 给所有有WhatsApp的买家发消息
- 输入 `全部两者` - 同时发邮件和WhatsApp
- 输入 `选择` - 选择特定买家发送
- 输入 `不发送` - 只查看，暂不发送

⚠️ 发送前请确保已在 `/设置` 中配置好邮箱！
"""
    ).send()

    cl.user_session.set("state", "waiting_for_channel")


# ==============================================================================
# 渠道选择和发送
# ==============================================================================

async def handle_channel_selection(content: str):
    """处理发送渠道选择"""
    content = content.strip()
    buyers = cl.user_session.get("current_buyers", [])
    task_id = cl.user_session.get("current_task_id", "")
    product_info = cl.user_session.get("product_info", {})

    if not buyers or not task_id:
        await cl.Message(content="没有找到买家数据，请重新搜索").send()
        cl.user_session.set("state", "waiting_for_product")
        return

    channel_map = {
        "全部邮件": "email",
        "全部whatsapp": "whatsapp",
        "全部两者": "both",
        "全部 邮件": "email",
    }

    if content in ("不发送", "跳过", "取消"):
        await cl.Message(content="✅ 已跳过发送。买家数据已保存，可随时在 `/历史` 中查看").send()
        cl.user_session.set("state", "waiting_for_product")
        return

    channel = channel_map.get(content.lower().strip(), None)

    if content.lower() in ("选择", "select"):
        await cl.Message(
            content="功能开发中，请输入 `全部邮件` 进行批量发送"
        ).send()
        return

    if not channel:
        await cl.Message(
            content="请输入：`全部邮件`、`全部WhatsApp`、`全部两者` 或 `不发送`"
        ).send()
        return

    # 过滤有效买家
    if channel == "email":
        valid_buyers = [b for b in buyers if b.get("email")]
    elif channel == "whatsapp":
        valid_buyers = [b for b in buyers if b.get("whatsapp")]
    else:
        valid_buyers = [b for b in buyers if b.get("email") or b.get("whatsapp")]

    if not valid_buyers:
        await cl.Message(
            content=f"⚠️ 没有符合条件的买家（{channel}渠道）"
        ).send()
        return

    await cl.Message(
        content=f"📤 准备通过 **{channel}** 发送给 **{len(valid_buyers)}** 家买家...\n⏳ 正在提交后台任务..."
    ).send()

    # 提交Celery发送任务
    try:
        from tasks.email_task import send_emails
        buyer_ids = [b["id"] for b in valid_buyers if b.get("id")]
        celery_task = send_emails.apply_async(
            args=[task_id, buyer_ids, product_info, channel],
            queue="email"
        )

        await cl.Message(
            content=f"""✅ **发送任务已提交！**

任务ID：`{celery_task.id}`
发送数量：**{len(buyer_ids)}** 家买家
渠道：**{channel}**

🔄 任务在后台运行，买家回复时会推送微信通知
输入 `/状态` 查看发送进度
"""
        ).send()

        cl.user_session.set("state", "waiting_for_product")
        cl.user_session.set("email_task_id", celery_task.id)

    except Exception as e:
        await cl.Message(
            content=f"❌ 任务提交失败：{e}\n请检查Celery Worker状态"
        ).send()


# ==============================================================================
# 命令实现
# ==============================================================================

async def show_settings():
    """显示设置页面"""
    cl.user_session.set("state", "settings")

    current_smtp = settings.SMTP_HOST or "未配置"
    current_imap = settings.IMAP_HOST or "未配置"
    current_wechat = "已配置 ✅" if settings.SERVERCHAN_SEND_KEY else "未配置"

    await cl.Message(
        content=f"""⚙️ **设置页面**

**当前配置状态：**
- SMTP邮箱（发送）：{current_smtp}
- IMAP邮箱（收件监控）：{current_imap}
- Server酱微信通知：{current_wechat}
- WhatsApp API：{"已配置 ✅" if settings.WHATSAPP_TOKEN else "未配置（可选）"}

---
**修改配置方式：**
请编辑项目根目录的 `.env` 文件，然后重启服务。

**SMTP示例（Gmail）：**
```
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your@gmail.com
SMTP_PASSWORD=your_app_password
SMTP_USE_TLS=true
```

**Server酱微信通知：**
1. 访问 https://sct.ftqq.com/
2. 微信扫码登录
3. 复制 SendKey 填入 .env 文件的 SERVERCHAN_SEND_KEY

**Gmail应用密码获取：**
谷歌账号 → 安全 → 两步验证 → 应用专用密码

输入 `返回` 退出设置
"""
    ).send()


async def show_history():
    """显示历史记录"""
    try:
        # 获取最近10个搜索任务
        tasks = await db.select(
            TABLE_SEARCH_TASKS,
            limit=10,
            order_by="created_at",
            order_desc=True
        )

        if not tasks:
            await cl.Message(content="📋 暂无历史记录").send()
            return

        history_text = "📋 **历史记录（最近10次搜索）：**\n\n"
        for task in tasks:
            status_icon = {
                "completed": "✅",
                "running": "⏳",
                "failed": "❌",
                "pending": "🔄",
                "timeout": "⏰"
            }.get(task.get("status", ""), "❓")

            created_at = task.get("created_at", "")[:10]
            history_text += (
                f"{status_icon} **{task.get('user_query', '未知')[:30]}...**\n"
                f"   时间：{created_at} | "
                f"结果：{task.get('result_count', 0)}家买家 | "
                f"状态：{task.get('status', '未知')}\n"
                f"   任务ID：`{task.get('task_id', '')}`\n\n"
            )

        # 获取最近回复
        replies = await db.select(
            TABLE_REPLIES,
            limit=5,
            order_by="created_at",
            order_desc=True
        )

        if replies:
            history_text += "---\n📧 **最近买家回复（最近5条）：**\n\n"
            for reply in replies:
                history_text += (
                    f"- **{reply.get('from_email', '')}** "
                    f"({reply.get('received_at', '')[:10]}): "
                    f"{reply.get('subject', '')[:50]}\n"
                )

        await cl.Message(content=history_text).send()

    except Exception as e:
        logger.error("获取历史记录失败", error=str(e))
        await cl.Message(content=f"获取历史记录失败：{e}").send()


async def show_help():
    """显示帮助"""
    await cl.Message(
        content="""📖 **帮助文档**

**基本使用流程：**
1. 输入产品描述（中英文均可）
2. 可选：上传产品PDF或粘贴产品链接
3. 选择搜索数量（100/200/300家）
4. 等待后台搜索完成（可关闭浏览器）
5. 选择发送渠道（邮件/WhatsApp/两者）
6. 接收微信通知（买家回复时）

**支持的命令：**
- `/设置` - 配置邮箱和微信通知
- `/历史` - 查看所有历史记录
- `/状态` - 查看当前任务状态
- `/取消` - 取消当前任务
- `/帮助` - 显示本帮助

**数据源（20个全球平台）：**
北美：ImportYeti, Piers.com, Thomasnet
欧洲：Kompass, Europages, Wlw.de, Kellysearch
中东：Zawya, TradeArabia
东南亚：TradeIndia, EC21, ExportersIndia
全球：Alibaba RFQ, Google, LinkedIn, TradeKey, TradeWheel, ExportHub等

**容错说明：**
- 任意数据源失败自动切换，保证稳定运行
- 任务在后台Celery运行，关闭浏览器不影响
- 所有数据存入Supabase，永久保存

**技术支持：**
GitHub: https://github.com/your-repo/GlobalMatch-Agent-V1
"""
    ).send()


async def show_current_status():
    """显示当前任务状态"""
    task_id = cl.user_session.get("current_task_id")
    if not task_id:
        await cl.Message(content="当前没有进行中的任务").send()
        return

    try:
        records = await db.select(TABLE_SEARCH_TASKS, {"task_id": task_id}, limit=1)
        if records:
            task = records[0]
            status = task.get("status", "unknown")
            progress = task.get("progress", 0)
            result_count = task.get("result_count", 0)

            status_icons = {"completed": "✅", "running": "⏳", "failed": "❌",
                            "pending": "🔄", "timeout": "⏰"}
            icon = status_icons.get(status, "❓")

            await cl.Message(
                content=f"""{icon} **当前任务状态**

任务ID：`{task_id}`
状态：{status}
进度：{progress}%
已找到买家：{result_count} 家
"""
            ).send()

            if status == "completed" and result_count > 0:
                await cl.Message(
                    content="任务已完成！输入 `展示结果` 重新显示买家列表"
                ).send()
    except Exception as e:
        await cl.Message(content=f"查询状态失败：{e}").send()


async def cancel_current_task():
    """取消当前任务"""
    celery_task_id = cl.user_session.get("celery_task_id")
    if celery_task_id:
        try:
            from tasks.celery_app import celery_app
            celery_app.control.revoke(celery_task_id, terminate=True)
            await cl.Message(content=f"✅ 任务 `{celery_task_id}` 已取消").send()
        except Exception as e:
            await cl.Message(content=f"取消失败：{e}").send()
    else:
        await cl.Message(content="没有可取消的任务").send()
    cl.user_session.set("state", "waiting_for_product")


async def handle_settings_input(content: str):
    """处理设置输入"""
    if content.strip() in ("返回", "back", "退出"):
        cl.user_session.set("state", "waiting_for_product")
        await cl.Message(content="已返回主界面，请输入你的产品描述").send()
    else:
        await cl.Message(
            content="请编辑 `.env` 文件修改配置，或输入 `返回` 退出设置"
        ).send()


# ==============================================================================
# 文件上传处理
# ==============================================================================

@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.AudioChunk):
    pass  # 不支持音频


# ==============================================================================
# FastAPI健康检查接口
# ==============================================================================

from fastapi import FastAPI
import uvicorn

api_app = FastAPI(title="GlobalMatch-Agent-V1 API")


@api_app.get("/health")
async def health_check():
    """健康检查接口"""
    try:
        # 检查Redis连接
        from redis import Redis
        r = Redis.from_url(settings.REDIS_URL)
        r.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    # 检查Supabase连接
    try:
        await db.select("search_tasks", limit=1)
        supabase_ok = True
    except Exception:
        supabase_ok = False

    return {
        "status": "healthy" if (redis_ok and supabase_ok) else "degraded",
        "redis": "ok" if redis_ok else "error",
        "supabase": "ok" if supabase_ok else "error",
        "version": "1.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


if __name__ == "__main__":
    # 直接运行Chainlit（开发模式）
    import subprocess
    subprocess.run(["chainlit", "run", "chainlit_app.py", "--host", "0.0.0.0", "--port", "8080"])
