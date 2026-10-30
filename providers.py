"""Explicit GLM or user-selected GPT provider; never silently switch services."""
from __future__ import annotations
import ipaddress
import re
import socket
import urllib.request
from urllib.parse import urlsplit

ZHIPU_BASE = "https://open.bigmodel.cn/api/paas/v4"
DEFAULT_MODEL = "glm-4.6"
OPENAI_BASE = "https://api.openai.com/v1"
GPT_MODEL = "gpt-4.1"
MICU_BASE = "https://www.micuapi.ai/v1"
MICU_MODEL = "gpt-6.1-sol"
MICU_GLM_MODEL = "glm-5.3-flash"
DEEPSEEK_BASE = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-flash"
PROVIDERS = ("智谱官方云 API", "内网本地 GLM", "OpenAI GPT API", "米醋中转 API（Responses）", "自部署 Qwen（结构化图文）", "DeepSeek 官方 API")


def endpoint(base_url, model, provider=PROVIDERS[0], resolve=True):
    model = model.strip()
    if provider == PROVIDERS[3]:
        if not re.fullmatch(r'(?:gpt-[a-z0-9._-]+|glm-[a-z0-9._-]+|qwen[a-z0-9._-]*|kimi-[a-z0-9._-]+)', model, re.I):
            raise ValueError('米醋模式请填写实际 GPT、GLM、Qwen 或 Kimi 模型标识')
    elif provider == PROVIDERS[2]:
        if not re.fullmatch(r'gpt-[a-z0-9._-]+', model, re.I):
            raise ValueError('GPT 模式请填写支持工具调用的实际 gpt- 模型标识')
    elif provider == PROVIDERS[4]:
        if not re.fullmatch(r'qwen[a-z0-9._/-]*', model, re.I):
            raise ValueError('自部署Qwen模式请填写实际qwen模型标识')
    elif provider == PROVIDERS[5]:
        if not re.fullmatch(r'deepseek-[a-z0-9._-]+', model):
            raise ValueError('DeepSeek 模式请填写官方实际 deepseek- 模型标识')
    elif not re.search(r"(?:^|[/_-])glm(?:[-_/]|$)", model, re.I) or "gpt" in model.lower():
            raise ValueError("当前 GLM 模式只接受 GLM 标识；GPT 请显式选择 OpenAI GPT API")
    parsed = urlsplit(base_url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ValueError("请填写完整模型服务地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("服务地址不能包含凭据、查询参数或片段")
    host = parsed.hostname.lower()
    if provider == PROVIDERS[0]:
        if host != "open.bigmodel.cn" or parsed.scheme != "https" or parsed.port not in (None, 443):
            raise ValueError("智谱官方云模式只允许 https://open.bigmodel.cn")
        if parsed.path.rstrip("/") not in ("/api/paas/v4", "/api/paas/v4/chat/completions"):
            raise ValueError("智谱官方云地址应为 " + ZHIPU_BASE)
    elif provider == PROVIDERS[2]:
        if host != 'api.openai.com' or parsed.scheme != 'https' or parsed.port not in (None,443):
            raise ValueError('GPT 模式只允许 https://api.openai.com')
        if parsed.path.rstrip('/') not in ('/v1','/v1/chat/completions'):
            raise ValueError('GPT 服务根地址应为 '+OPENAI_BASE)
    elif provider == PROVIDERS[3]:
        if host != 'www.micuapi.ai' or parsed.scheme != 'https' or parsed.port not in (None, 443):
            raise ValueError('米醋中转模式只允许 https://www.micuapi.ai')
        if parsed.path.rstrip('/') not in ('/v1', '/v1/responses'):
            raise ValueError('米醋服务根地址应为 '+MICU_BASE)
    elif provider == PROVIDERS[1]:
        if host.endswith(("openai.com", "bigmodel.cn")):
            raise ValueError("内网模式必须连接企业内网的 GLM 服务")
        if resolve:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or 80, type=socket.SOCK_STREAM)}
            networks = tuple(ipaddress.ip_network(n) for n in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "::1/128", "fc00::/7"))
            if not addresses or any(not any(ipaddress.ip_address(a) in n for n in networks if ipaddress.ip_address(a).version == n.version) for a in addresses):
                raise ValueError("内网 GLM 地址必须解析为回环地址或企业私网地址")
    elif provider == PROVIDERS[4]:
        if parsed.path.rstrip('/') not in ('/v1', '/v1/chat/completions'):
            raise ValueError('自部署Qwen地址应以/v1结尾')
    elif provider == PROVIDERS[5]:
        if host != 'api.deepseek.com' or parsed.scheme != 'https' or parsed.port not in (None, 443):
            raise ValueError('DeepSeek 官方模式只允许 https://api.deepseek.com')
        if parsed.path.rstrip('/') not in ('', '/v1', '/chat/completions', '/v1/chat/completions'):
            raise ValueError('DeepSeek 服务根地址应为 '+DEEPSEEK_BASE)
    else:
        raise ValueError("未知模型部署方式")
    if provider == PROVIDERS[3]:
        return base_url.strip().rstrip('/') if parsed.path.rstrip('/').endswith('/responses') else base_url.strip().rstrip('/')+'/responses'
    return base_url.strip().rstrip("/") if parsed.path.rstrip("/").endswith("/chat/completions") else base_url.strip().rstrip("/") + "/chat/completions"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("模型服务发生重定向，已停止请求；请检查服务地址")


def open_request(request, provider, timeout=90):
    handlers = [NoRedirect()]
    if provider in (PROVIDERS[1], PROVIDERS[4]):
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers).open(request, timeout=timeout)
