"""Unauthenticated connectivity checks; no questions or documents are sent."""
import os
import socket
from urllib.parse import urlparse
import httpx
from dotenv import dotenv_values

values = dotenv_values('D:/pycharmproject/LangChain1/.env')
print('Proxy endpoints:', {k: urlparse(v).hostname for k, v in os.environ.items() if 'PROXY' in k.upper()})
for key in ('OPENAI_BASE_URL', 'DEEPSEEK_BASE_URL'):
    endpoint = values.get(key)
    if not endpoint:
        continue
    parsed = urlparse(endpoint)
    print(key, parsed.scheme, parsed.hostname, parsed.path)
    try:
        print('DNS:', socket.getaddrinfo(parsed.hostname, 443)[0][4][0])
        with socket.create_connection((parsed.hostname, 443), timeout=6):
            print('TCP: OK')
    except Exception as error:
        print('TCP:', type(error).__name__, str(error))
    for trust_env in (True, False):
        try:
            with httpx.Client(timeout=8, trust_env=trust_env) as client:
                result = client.get(f'{parsed.scheme}://{parsed.netloc}/')
                print('HTTP trust_env=', trust_env, 'status=', result.status_code)
        except Exception as error:
            print('HTTP trust_env=', trust_env, type(error).__name__, str(error))
