"""
PDF解析模块 - 使用PyMuPDF提取产品信息
"""
import re
import structlog
from pathlib import Path
from typing import Optional
import fitz  # PyMuPDF

logger = structlog.get_logger(__name__)


class PDFParser:
    """PyMuPDF PDF解析器"""

    MAX_FILE_SIZE_MB = 50
    MAX_PAGES = 100

    def parse(self, file_path: str | Path) -> dict:
        """
        解析PDF文件，提取产品信息
        返回: {text, product_name, specs, selling_points, keywords}
        """
        file_path = Path(file_path)
        if not file_path.exists():
            logger.error("PDF文件不存在", path=str(file_path))
            return self._empty_result()

        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.MAX_FILE_SIZE_MB:
            logger.warning("PDF文件过大", size_mb=file_size_mb)
            return self._empty_result("文件过大，超过50MB限制")

        try:
            doc = fitz.open(str(file_path))
            pages_to_read = min(doc.page_count, self.MAX_PAGES)
            full_text = []

            for page_num in range(pages_to_read):
                try:
                    page = doc[page_num]
                    text = page.get_text("text")
                    if text.strip():
                        full_text.append(text)
                except Exception as e:
                    logger.warning("PDF页面读取失败", page=page_num, error=str(e))
                    continue

            doc.close()

            combined_text = "\n".join(full_text)
            if not combined_text.strip():
                return self._empty_result("PDF内容为空")

            result = self._extract_product_info(combined_text)
            result["raw_text"] = combined_text[:5000]  # 截取前5000字符
            result["page_count"] = pages_to_read
            logger.info("PDF解析成功", pages=pages_to_read, chars=len(combined_text))
            return result

        except fitz.FileDataError as e:
            logger.error("PDF格式错误", error=str(e))
            return self._empty_result(f"PDF格式错误: {e}")
        except Exception as e:
            logger.error("PDF解析异常", error=str(e))
            return self._empty_result(f"解析异常: {e}")

    def parse_bytes(self, pdf_bytes: bytes) -> dict:
        """从字节流解析PDF"""
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            pages_to_read = min(doc.page_count, self.MAX_PAGES)
            full_text = []

            for page_num in range(pages_to_read):
                try:
                    page = doc[page_num]
                    text = page.get_text("text")
                    if text.strip():
                        full_text.append(text)
                except Exception as e:
                    logger.warning("PDF页面读取失败", page=page_num, error=str(e))

            doc.close()
            combined_text = "\n".join(full_text)
            result = self._extract_product_info(combined_text)
            result["raw_text"] = combined_text[:5000]
            return result

        except Exception as e:
            logger.error("PDF字节流解析失败", error=str(e))
            return self._empty_result(str(e))

    def _extract_product_info(self, text: str) -> dict:
        """从文本中提取产品关键信息"""
        lines = [line.strip() for line in text.split("\n") if line.strip()]

        # 提取产品名（通常在标题位置，首行或大写行）
        product_name = self._extract_product_name(lines)
        # 提取规格参数
        specs = self._extract_specs(text)
        # 提取卖点
        selling_points = self._extract_selling_points(text)
        # 提取关键词
        keywords = self._extract_keywords(text)

        return {
            "product_name": product_name,
            "specs": specs,
            "selling_points": selling_points,
            "keywords": keywords,
            "raw_text": "",
            "page_count": 0,
            "error": None
        }

    def _extract_product_name(self, lines: list[str]) -> str:
        """提取产品名"""
        # 优先取前5行中较长的行（通常是标题）
        candidates = []
        for line in lines[:10]:
            if 3 < len(line) < 100:
                candidates.append(line)
        if candidates:
            # 优先选择含有产品相关关键词的行
            product_keywords = ["product", "model", "type", "series", "系列", "产品", "型号"]
            for line in candidates:
                if any(kw in line.lower() for kw in product_keywords):
                    return line
            return candidates[0]
        return "未知产品"

    def _extract_specs(self, text: str) -> list[str]:
        """提取规格参数"""
        specs = []
        # 匹配规格行：含有数字+单位的行
        spec_patterns = [
            r'(?:规格|spec|size|dimension|capacity|power|voltage|weight|length|width|height)[:\s]+.+',
            r'\d+[\.\d]*\s*(?:mm|cm|m|kg|g|lb|oz|W|V|A|Hz|MHz|GHz|L|ml|inch|ft)',
            r'(?:Model|型号|SKU)[:\s]+\w+',
        ]
        for pattern in spec_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            specs.extend(matches[:5])
        return list(set(specs))[:20]

    def _extract_selling_points(self, text: str) -> list[str]:
        """提取卖点"""
        selling_points = []
        # 查找bullet points和优势描述
        bullet_pattern = r'[•·✓✗→\-\*]\s*(.{10,100})'
        matches = re.findall(bullet_pattern, text)
        selling_points.extend(matches[:10])

        # 查找含有优势词的句子
        advantage_words = ["advantage", "feature", "benefit", "why choose", "优势", "特点", "特色"]
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if any(word in line.lower() for word in advantage_words):
                if i + 1 < len(lines):
                    selling_points.append(lines[i + 1].strip())

        return [sp for sp in selling_points if len(sp) > 5][:15]

    def _extract_keywords(self, text: str) -> list[str]:
        """提取搜索关键词"""
        keywords = []
        # 提取英文单词（2-20字符，去掉常见停用词）
        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "been",
                      "have", "has", "had", "do", "does", "did", "will", "would",
                      "could", "should", "may", "might", "shall", "can", "and",
                      "or", "but", "in", "on", "at", "to", "for", "of", "with",
                      "by", "from", "as", "into", "through", "during", "including",
                      "until", "against", "among", "throughout", "despite", "towards"}

        words = re.findall(r'\b[A-Za-z][A-Za-z\-]{1,19}\b', text)
        word_freq = {}
        for word in words:
            word_lower = word.lower()
            if word_lower not in stop_words and len(word) > 2:
                word_freq[word_lower] = word_freq.get(word_lower, 0) + 1

        # 取频率最高的关键词
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        keywords = [word for word, freq in sorted_words[:20] if freq >= 2]
        return keywords

    def _empty_result(self, error: str = "") -> dict:
        return {
            "product_name": "",
            "specs": [],
            "selling_points": [],
            "keywords": [],
            "raw_text": "",
            "page_count": 0,
            "error": error
        }


# 全局单例
pdf_parser = PDFParser()
