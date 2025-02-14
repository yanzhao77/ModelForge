import requests
from openai import OpenAI, NotFoundError


def get_localhost():
    # test interface
    # API 地址
    API_URL = "http://localhost:7783/v1/chat/completions"

    # 认证信息
    HEADERS = {
        "Authorization": "Bearer valid_api_key",
        "Content-Type": "application/json"
    }

    # 请求数据
    DATA = {
        "model": "DeepSeek-R1-Distill-Qwen-1.5B",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "temperature": 0.7
    }

    # 发送 POST 请求
    response = requests.post(API_URL, headers=HEADERS, json=DATA)

    # 打印结果
    print("Status Code:", response.status_code)
    print("Response JSON:", response.json())


def get_localhost_model():
    base_url = "http://localhost:7783/v1"  # 修正1：添加版本路径
    api_key = "valid_api_key"  # 修正2：去掉Bearer前缀

    client = OpenAI(
        api_key=api_key,
        base_url=base_url
    )

    try:
        completion = client.chat.completions.create(
            model='DeepSeek-R1-Distill-Qwen-1.5B',
            messages=[
                {"role": "system", "content": "你是一个资深程序员"},
                {"role": "user", "content": "说一个程序员才懂的笑话"}
            ],
            top_p=0.7,
            temperature=0.9
        )
        print(completion.choices[0].message)
    except Exception as e:
        print(f"Error: {e}")
        if hasattr(e, 'response'):
            print(e.response.text)


if __name__ == '__main__':
    get_localhost_model()
