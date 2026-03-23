"""global_buyer_pipeline 全局配置"""
import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
COMTRADE_API_KEY = os.getenv("COMTRADE_API_KEY", "")

# UN Comtrade 限制：每次调用间隔1秒
COMTRADE_DELAY = 1.0

# HS 编码列表（覆盖所有品类）
HS_CODES = {
    "服装": [61, 62, 63],
    "电子": [84, 85],
    "玩具": [95],
    "户外运动": [94, 9506],
    "设备机械": [82, 83, 84],
    "装饰家居": [94, 70, 69],
    "材料原料": [39, 40, 72, 76],
    "其他消费品": [64, 65, 66, 67],
}
