import requests
import json

# 登录
token = requests.post('http://localhost:8000/api/v1/auth/login', 
    json={'username': 'admin', 'password': 'admin123'}).json()['data']['access_token']

# JSON导出
res = requests.post('http://localhost:8000/api/v1/extractions/export',
    json={'task_ids': ['442445d1-b0c7-4b06-beda-c36d1af0f89a'], 'format': 'json'},
    headers={'Authorization': f'Bearer {token}'})

if res.status_code == 200:
    key = res.json()['data']['object_key']
    print(f"✓ JSON导出成功，对象键: {key[:30]}...")
    
    # 下载
    dl = requests.get(f'http://localhost:8000/api/v1/extractions/exports/download?object_key={key}',
        headers={'Authorization': f'Bearer {token}'})
    data = json.loads(dl.text)
    print(f"✓ 下载完成: {len(data)}条记录，每条一行")
    print(f"✓ 第一条记录keys: {list(data[0].keys())[:5]}...")
else:
    print(f"✗ 失败: {res.status_code}")
