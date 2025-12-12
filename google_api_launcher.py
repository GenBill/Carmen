
import os
from PIL import Image
from google import genai
from google.genai import types

from auto_proxy import setup_proxy_if_needed
setup_proxy_if_needed(clash_port=7897)

# 使用新版 google-genai SDK 的 safety_settings 格式
NSFW_SETTING = [
    types.SafetySetting(
        category="HARM_CATEGORY_HATE_SPEECH",
        threshold="OFF"
    ),
    types.SafetySetting(
        category="HARM_CATEGORY_HARASSMENT", 
        threshold="OFF"
    ),
]

# 配置 API Key
# 建议将 KEY 放在环境变量中，或者直接替换下方的字符串
os.environ["GOOGLE_API_KEY"] = open("agent/gemini.token", "r").read().strip()
os.environ.pop("GEMINI_API_KEY", None)  # 移除冲突的环境变量，避免警告

def call_gemini(prompt_text, client=None):
    if client == None:
        client = genai.Client()
    chat = client.chats.create(
        model="gemini-2.5-flash",
        config=types.GenerateContentConfig(
            response_modalities=['TEXT'],  # gemini-2.5-flash 只支持文本输出
            tools=[{"google_search": {}}],
            safety_settings=NSFW_SETTING
        )
    )
    message = [prompt_text]
    response = chat.send_message(message)
    return response.text, client

def call_banana(prompt_text, image_path_list, client=None, output_path="gemini_studio/output.png"):
    if client == None:
        client = genai.Client()
    chat = client.chats.create(
        model="gemini-3-pro-image-preview",
        config=types.GenerateContentConfig(
            response_modalities=['TEXT', 'IMAGE'],
            tools=[{"google_search": {}}],
            safety_settings=NSFW_SETTING
        )
    )
    
    message = [prompt_text]
    for image_path in image_path_list:
        image = Image.open(image_path)
        message.append(image)
    response = chat.send_message(message)

    if response.parts == None:
        print("No response from Banana API.")
        return None

    for part in response.parts:
        if part.text is not None:
            print(part.text)
        elif output_image := part.inline_data:
            # 处理返回的图像数据
            from io import BytesIO
            img = Image.open(BytesIO(output_image.data))
            img.save(output_path)
    
    print(f'Image has been saved to: {output_path}')
    return client


# google_api_launcher.py
if __name__ == "__main__":
    
    prompt = "请用一句话解释什么是量子计算。"
    response, client = call_gemini(prompt)
    print(response)

    # prompt = "请帮我对这张图像进行超分辨率。"
    # image_list = ['gemini_studio/test.jpg']
    # output_path = 'gemini_studio/output.png'
    # client = call_banana(prompt, image_list, output_path=output_path)

    print("All Test Done!")


