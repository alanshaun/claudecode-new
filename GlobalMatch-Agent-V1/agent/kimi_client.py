"""
Kimi API封装（兼容OpenAI格式）
base_url=https://api.moonshot.cn/v1
model=moonshot-v1-8k
"""
import asyncio
import structlog
from typing import Optional
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from config import settings

logger = structlog.get_logger(__name__)


class KimiClient:
    """Kimi API客户端，兼容OpenAI格式"""

    def __init__(self):
        self.client = AsyncOpenAI(
            api_key=settings.KIMI_API_KEY,
            base_url=settings.KIMI_BASE_URL,
        )
        self.model = settings.KIMI_MODEL

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type(Exception)
    )
    async def chat(self, messages: list[dict], temperature: float = 1.0,
                   max_tokens: int = 2000) -> str:
        """
        发送对话请求
        返回: 助手回复文本
        """
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            content = response.choices[0].message.content
            logger.debug("Kimi响应", tokens=response.usage.total_tokens if response.usage else 0)
            return content or ""
        except Exception as e:
            logger.error("Kimi API调用失败", error=str(e))
            raise

    async def analyze_product_query(self, user_query: str,
                                     product_context: str = "") -> dict:
        """
        分析用户输入，生成搜索参数
        返回: {keywords, target_countries, buyer_types, product_summary}
        """
        system_prompt = """你是一个专业的外贸买家搜索分析师。
用户是中国卖家，输入自然语言描述产品，你需要生成精准的搜索参数用于全球买家搜索。
请用JSON格式返回，包含以下字段：
{
  "product_summary": "产品简短描述（中文，50字以内）",
  "keywords_en": ["英文关键词1", "英文关键词2", ...],  // 3-6个，用于搜索
  "target_countries": ["USA", "Germany", "UK", ...],  // 5-10个最有潜力的国家
  "buyer_types": ["importer", "wholesaler", "distributor", "retailer"],
  "industry": "所属行业（英文）",
  "hs_code_hint": "可能的HS编码（如果能判断）",
  "search_queries": ["搜索短语1", "搜索短语2", ...]  // 用于Google搜索的完整短语
}
只返回JSON，不要有其他文字。"""

        user_message = f"产品描述：{user_query}"
        if product_context:
            user_message += f"\n\nPDF/链接提取的产品信息：{product_context[:2000]}"

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        try:
            response = await self.chat(messages, temperature=1.0)
            # 解析JSON
            import json
            # 提取JSON部分（防止模型输出多余文字）
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                result = json.loads(response[json_start:json_end])
                return result
            else:
                logger.warning("Kimi返回非JSON格式", response=response[:200])
                return self._default_search_params(user_query)
        except Exception as e:
            logger.error("产品分析失败", error=str(e))
            return self._default_search_params(user_query)

    async def generate_email(self, product_info: dict, buyer_info: dict) -> dict:
        """
        生成个性化英文开发信
        返回: {subject, body}
        """
        system_prompt = """你是一个专业的外贸业务员，擅长写简洁有效的英文开发信。
规则：
1. 引用买家公司名和国家，体现个性化
2. 简要介绍产品核心优势（不超过3点）
3. 不要编造任何采购记录或虚假信息
4. 语气专业、友好，避免过度推销
5. 结尾有清晰的CTA（行动号召）
6. 邮件正文控制在150-250字
请用JSON格式返回：
{"subject": "邮件主题（英文）", "body": "邮件正文（英文）"}
只返回JSON。"""

        user_message = f"""
产品信息：
- 产品名：{product_info.get('product_name', '')}
- 行业：{product_info.get('industry', '')}
- 卖点：{', '.join(product_info.get('selling_points', [])[:3])}
- 规格：{', '.join(product_info.get('specs', [])[:3])}

买家信息：
- 公司名：{buyer_info.get('company_name', '')}
- 国家：{buyer_info.get('country', '')}
- 品类：{buyer_info.get('categories', ['未知'])[0] if buyer_info.get('categories') else '未知'}
"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ]

        try:
            response = await self.chat(messages, temperature=1.0)
            import json
            json_start = response.find("{")
            json_end = response.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                return json.loads(response[json_start:json_end])
            else:
                return self._default_email(buyer_info, product_info)
        except Exception as e:
            logger.error("邮件生成失败", error=str(e))
            return self._default_email(buyer_info, product_info)

    async def expand_keywords(self, original_keywords: list[str],
                               insufficient_count: int) -> list[str]:
        """关键词不足时扩展搜索词"""
        prompt = f"""原始搜索关键词：{', '.join(original_keywords)}
当前搜索结果不足（只找到{insufficient_count}家买家）。
请生成5个扩展关键词，包括：同义词、相关品类、上下游产品。
只返回JSON数组：["keyword1", "keyword2", ...]"""

        messages = [{"role": "user", "content": prompt}]
        try:
            response = await self.chat(messages, temperature=1.0)
            import json
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except Exception as e:
            logger.error("关键词扩展失败", error=str(e))
        return []

    def _default_search_params(self, query: str) -> dict:
        """默认搜索参数（Kimi失败时的降级）"""
        words = query.split()[:3]
        return {
            "product_summary": query[:50],
            "keywords_en": words,
            "target_countries": ["USA", "Germany", "UK", "Australia", "Canada"],
            "buyer_types": ["importer", "wholesaler", "distributor"],
            "industry": "general",
            "hs_code_hint": "",
            "search_queries": [f"{' '.join(words)} importer", f"{' '.join(words)} wholesaler"]
        }

    def _default_email(self, buyer: dict, product: dict) -> dict:
        """默认邮件模板（生成失败时的降级）"""
        company = buyer.get("company_name", "your company")
        country = buyer.get("country", "")
        product_name = product.get("product_name", "our products")

        return {
            "subject": f"Quality {product_name} Supplier - Partnership Opportunity",
            "body": f"""Dear {company} Team,

I hope this message finds you well. I am reaching out from a leading Chinese manufacturer
specializing in {product_name}.

We noticed that your company in {country} might be interested in sourcing quality {product_name}.
We offer competitive pricing, reliable quality, and fast delivery.

Key advantages:
- Competitive factory-direct pricing
- ISO certified quality management
- Fast delivery (15-30 days)

I would love to discuss how we can support your business needs.
Could we schedule a brief call or exchange product details?

Looking forward to your response.

Best regards,
Business Development Team"""
        }


# 全局单例
kimi_client = KimiClient()
