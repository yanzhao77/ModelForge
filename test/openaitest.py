import os
import requests
from openai import OpenAI

api_key = os.getenv("OPENAI_API_KEY", "sk-CsUwFWsagU5IwyAcZhPBKs3ks1TcOlLUXgoBl9FoXB7KKW")
base_urls  = ["https://api.chatanywhere.tech/v1", "https://api.chatanywhere.com.cn/v1"]
client = OpenAI(api_key=api_key, base_url=base_urls[0])

def get_model_list():
    url = base_urls[0] + "/models"
    headers = {
        'Authorization': f'Bearer {api_key}',
        'User-Agent': 'Apifox/1.0.0 (https://apifox.com)'
        }
    response = requests.request("GET", url, headers=headers)
    data = response.json()['data']
    models = [model['id'] for model in data]
    print(models)

# 非流式响应
def chat(model="gpt-3.5-turbo", messages=[], temperature=0.7):
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        )
    return completion.choices[0].message.content

# 流式响应
def chat_stream(model="gpt-3.5-turbo", messages=[], temperature=0.7):
    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        stream=True,
        )
    for chunk in completion:
        if chunk.choices[0].delta.content is not None:
            yield chunk.choices[0].delta.content

if __name__ == '__main__':
    messages = [
    {'role': 'system', 'content': '你是百科全书'}, # 人设提示词，可以不添加
    {'role': 'user','content': '鲁迅和周树人的关系'},
    ]
    # res = chat(model="gpt-3.5-turbo", messages=messages)
    # print(res)
    for text in chat_stream(model="gpt-3.5-turbo", messages=messages):
        print(text, end='')