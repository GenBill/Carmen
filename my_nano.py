import time
from google_api_launcher import call_gemini, call_banana

def main_yanqing():

    date_str = time.strftime("%Y%m%d%H%M%S")

    prompt = """
        请帮我用水浒传的风格生成一段文生图提示词，描写水浒传中燕青的人物立绘。
        使用的模型是Gemini 2.5 Flash Image (Nano Banana)，因此提示词可以使用流畅连贯的自然语言。
        画面中不要包含说明文字。你的输出将会直接灌入生成模型，不要包含任何说明，直接输出中文提示词。
    """
    response, client = call_gemini(prompt, model="gemini-3-pro-preview")
    print(response)

    prompt = f"{response}"
    image_list = []
    output_path = f'gemini_studio/output-{date_str}.png'
    client = call_banana(prompt, image_list, output_path=output_path)

def main_youle():

    date_str = time.strftime("%Y%m%d%H%M%S")

    prompt = """
        请帮我用JOJO的风格生成一段文生图提示词，描写水浒传中火眼狻猊邓飞的立绘。
        使用的模型是Gemini 2.5 Flash Image (Nano Banana)，因此提示词可以使用流畅连贯的自然语言。
        画面中不要包含说明文字。你的输出将会直接灌入生成模型，不要包含任何说明，直接输出中文提示词。
    """
    response, client = call_gemini(prompt, model="gemini-3-pro-preview")
    print(response)

    prompt = f"{response}"
    image_list = []
    output_path = f'gemini_studio/output-{date_str}.png'
    client = call_banana(prompt, image_list, output_path=output_path)


if __name__ == "__main__":

    # main_yanqing()
    main_youle()

#     youle_prompt = """一张极具荒木飞吕彦（Araki Hirohiko）艺术风格的《巴拉拉小魔仙》游乐王子全身立绘。画面应当展现出《JOJO的奇妙冒险》标志性的硬朗线条、夸张透视和戏剧性张力。

# 游乐王子身穿经过“JOJO化”改造的蓝金色华丽宫廷战斗制服，垫肩高耸，衣褶刻画有着浓重的黑色墨线和交叉排线阴影（Cross-hatching），凸显出服装下结实的肌肉轮廓。他戴着标志性的蓝色半脸面具，露出的下颚线条如刀削般锋利棱角分明，嘴唇厚实且带有风格化的阴影，眼神透过面具散发出摄人心魄的锐利光芒，仿佛正在发动替身攻击。

# 他摆出了一个极其扭曲且不符合人体工学的经典“JOJO立”（JoJo Pose），脊柱夸张地后仰，一只手遮挡在额头前，手指姿态修长且有力；另一只手举起他的标志性魔法枪指向观众准备射击。背景采用高饱和度的对比色调，融合了迷幻的波普艺术图案和放射状的速度线，营造出一种强烈的压迫感和时髦值爆表的氛围，光影对比极其强烈，色彩鲜艳且富有冲击力。"""
    
#     date_str = time.strftime("%Y%m%d%H%M%S")
#     output_path = f'gemini_studio/output-{date_str}.png'
#     client = call_banana(youle_prompt, [], output_path=output_path)

