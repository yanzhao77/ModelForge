import os
import time
import uuid
from wsgiref import simple_server

import falcon
from pytorch.model_generate import model_generate


class FalconOpenAIChatCompletionResource:
    def __init__(self):
        self.model = None
        self.app = falcon.App()
        self.app.add_route('/v1/chat/completions', self)
        self.run()

    def run(self):
        httpd = simple_server.make_server('localhost', 7783, self.app)
        print("Serving OpenAI-compatible API on port 7783...")
        httpd.serve_forever()

    def validate_api_key(self, auth_header):
        if not auth_header:
            return False
        parts = auth_header.split()
        return len(parts) == 2 and parts[0].lower() == 'bearer' and parts[1] == 'valid_api_key'

    def on_post(self, req, resp):
        # Authentication
        auth_header = req.get_header('Authorization')
        if not self.validate_api_key(auth_header):
            resp.status = falcon.HTTP_401
            resp.media = {"error": "Invalid authentication"}
            return

        # Parse request
        try:
            request_data = req.get_media()
            messages = request_data['messages']
            self.model_name = request_data.get('model', 'default-model')
            if self.model is None:
                local_model_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'model')
                self.model = model_generate(model_path=os.path.join(local_model_path, self.model_name))
                self.model.pipeline_question()
            temperature = request_data.get('temperature', 0.7)
        except KeyError:
            resp.status = falcon.HTTP_400
            resp.media = {"error": "Missing required parameter: messages"}
            return

        # Validate messages
        if not messages or messages[-1]['role'] != 'user':
            resp.status = falcon.HTTP_400
            resp.media = {"error": "Last message must be from user"}
            return

        # Extract conversation context
        user_message = messages[-1]
        self.merge_messages(self.model.message_dict, messages)
        self.model.message_dict.remove(messages[-1])
        # Generate response
        try:
            response_text = self.model.pipeline_answer(messages[-1]['content'])
        except Exception as e:
            resp.status = falcon.HTTP_500
            resp.media = {"error": str(e)}
            return

        # Build OpenAI-style response
        resp.media = {
            "id": f"chatcmpl-{uuid.uuid4()}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": self.model_name,
            "choices": [{
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_text
                },
                "finish_reason": "stop"
            }],
            "usage": {
                "prompt_tokens": len(user_message['content'].split()),
                "completion_tokens": len(response_text.split()),
                "total_tokens": len(user_message['content'].split()) + len(response_text.split())
            }
        }
        resp.status = falcon.HTTP_200

    def merge_messages(self, messages_dict, messages_temp):
        existing_messages = {tuple(msg.items()) for msg in messages_dict}  # 将已有的消息转换为不可变集合
        for msg in messages_temp:
            if tuple(msg.items()) not in existing_messages:
                messages_dict.append(msg)  # 只添加不同的消息
        return messages_dict
