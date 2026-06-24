import json
import urllib.request
from urllib.parse import quote

group = "🚀 节点选择"
node = "🇯🇵 日本 03 电信/沪日专线（3倍率）"

url = "http://127.0.0.1:9090/proxies/" + quote(group, safe="")
req = urllib.request.Request(
    url,
    data=json.dumps({"name": node}).encode(),
    method="PUT",
    headers={"Content-Type": "application/json"},
)
print(urllib.request.urlopen(req).status)