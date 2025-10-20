from cgi import test
import os
from openai import OpenAI

class DeepSeekAPI:
    def __init__(
        self, 
        token_path="agent/deepseek.token", 
        system_prompt="You are a helpful assistant"
    ):
        # Load DeepSeek API key from file
        with open(token_path, "r") as file:
            self.mytoken = file.read().strip()
        self.client = OpenAI(
            api_key = self.mytoken,
            base_url = "https://api.deepseek.com")
        
        self.system_prompt = system_prompt
        self.dialog = []
        self.dialog.append({"role": "system", "content": system_prompt})
        self.model_type = "deepseek-chat"
        # self.model_type = "deepseek-reasoner"
    
    def recursive_call(self, user_prompt):
        self.dialog.append({"role": "user", "content": user_prompt})
        response = self.client.chat.completions.create(
            model = self.model_type, 
            messages = self.dialog,
            stream = False
        )
        response_content = response.choices[0].message.content
        self.dialog.append({"role": "assistant", "content": response_content})
        return response_content
    
    def __call__(self, user_prompt):
        response = self.client.chat.completions.create(
            model = self.model_type,
            messages = [{"role": "user", "content": user_prompt}],
            stream = False
        )
        response_content = response.choices[0].message.content
        return response_content

if __name__ == "__main__":
    
    deepseek = DeepSeekAPI()

    print('Token Test OK!')
    
    # response = deepseek("Hello, how are you?")
    # print(response)
    # response = deepseek("What is the capital of France?")
    # print(response)

    # print(deepseek.dialog)

