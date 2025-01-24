from openai import OpenAI

client = OpenAI(
    api_key="sk-n6baYpMJ3RavbiIf71H0gla1XP6phoNsw1EKJm33mtEUUfas",
    base_url="https://api.xiaoai.plus/v1",
)

completion = client.chat.completions.create(
  model="gpt-3.5-turbo",
  messages=[
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "Hello!"}
  ]
)

print(completion.choices[0].message)
