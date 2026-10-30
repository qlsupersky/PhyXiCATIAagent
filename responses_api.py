"""Responses wire adapter, preserving complete output items across tool turns."""
import json
import urllib.request
from providers import endpoint, open_request


def input_items(messages):
    items = []
    for message in messages:
        role = message['role']
        if role == 'system':
            continue
        if role == 'tool':
            items.append({'type': 'function_call_output', 'call_id': message['tool_call_id'], 'output': message['content']})
        elif role == 'assistant' and message.get('responses_output') is not None:
            items.extend(message['responses_output'])
        elif role == 'assistant':
            if message.get('content'):
                items.append({'role': 'assistant', 'content': message['content']})
            for call in message.get('tool_calls', []):
                items.append({'type': 'function_call', 'call_id': call['id'], **call['function']})
        else:
            content=message['content']
            if isinstance(content,list):
                converted=[]
                for block in content:
                    if block['type']=='text':converted.append({'type':'input_text','text':block['text']})
                    elif block['type']=='image_url':
                        value=block['image_url']
                        converted.append({'type':'input_image','image_url':value['url'],'detail':value.get('detail','high')})
                    else:raise ValueError('不支持的图像消息块')
                content=converted
            items.append({'role': role, 'content': content})
    return items


def events(response):
    data = []
    for line in response:
        line = line.decode('utf-8-sig').rstrip('\r\n')
        if not line:
            if data:
                value = '\n'.join(data)
                data.clear()
                if value != '[DONE]':
                    yield json.loads(value)
            continue
        if line.startswith('data:'):
            data.append(line[5:].lstrip())
    if data and '\n'.join(data) != '[DONE]':
        yield json.loads('\n'.join(data))


def request_responses(base_url, key, model, messages, tools, provider, controller, emit):
    if not key:
        raise ValueError('请在插件内填写米醋 API Key，或从 CC Switch 读取当前配置')
    payload = {'model': model, 'instructions': '\n'.join(m['content'] for m in messages if m['role'] == 'system'),
               'input': input_items(messages), 'stream': True, 'store': False,
               'tools': [{'type': 'function', **tool, 'strict': False} for tool in tools]}
    # Encrypted reasoning replay is a GPT option; other Micu routes may reject it.
    if model.lower().startswith('gpt-'):
        payload['include'] = ['reasoning.encrypted_content']
    request = urllib.request.Request(endpoint(base_url, model, provider), json.dumps(payload).encode('utf-8'),
                                     {'Content-Type': 'application/json', 'Accept': 'text/event-stream',
                                      'User-Agent': 'PhyXiCATIAAgent/0.5.2', 'Authorization': 'Bearer '+key})
    final = None
    emitted = False
    with open_request(request, provider) as response:
        if 'text/event-stream' not in response.headers.get('Content-Type', ''):
            final = json.load(response)
        else:
            for event in events(response):
                if controller.cancel.is_set():
                    raise RuntimeError('智能体任务已中止')
                kind = event.get('type')
                if kind == 'response.output_text.delta':
                    emit(event.get('delta', ''))
                    emitted = True
                elif kind == 'response.completed':
                    final = event['response']
                elif kind in ('response.failed', 'response.incomplete', 'error'):
                    raise RuntimeError('Responses服务返回失败或不完整响应；未将远端错误正文写入日志')
    if not final or final.get('status') != 'completed':
        raise RuntimeError('Responses响应未完整结束；未执行其中的工具调用')
    output = final.get('output', [])
    content = ''.join(part.get('text', '') for item in output if item.get('type') == 'message'
                      for part in item.get('content', []) if part.get('type') == 'output_text')
    calls = [{'id': item['call_id'], 'type': 'function', 'function': {'name': item['name'], 'arguments': item['arguments']}}
             for item in output if item.get('type') == 'function_call']
    if not calls and not content:
        raise RuntimeError('Responses服务未返回可显示文本或工具调用')
    if not emitted and content:
        emit(content)
    message = {'role': 'assistant', 'content': content or None, 'responses_output': output,
               'response_metadata': {name: final.get(name) for name in ('id', 'model', 'status', 'usage')}}
    if calls:
        message['tool_calls'] = calls
    return message
