from flask import Flask, request, Response
import requests
from urllib.parse import urlparse
import base64
import re
import config
import socket
from socket import inet_aton
from struct import unpack

app = Flask(__name__)

@app.route('/')
def index():
	return "hello world!"


regex_pattern = re.compile(r'([\w\-_]+\.)?([\w\-_]+(\.[\w\-_]+)+)')
def extract_main_domain(url):
    match = regex_pattern.search(url)
    if match:
        return match.group(2)
    return url


def ip2long(ip_addr):
    return unpack("!L", inet_aton(ip_addr))[0]


def is_inner_ipaddress(ip):
    ip = ip2long(ip)
    return ip2long("127.0.0.0") >> 24 == ip >> 24 or \
        ip2long("10.0.0.0") >> 24 == ip >> 24 or \
        ip2long("172.16.0.0") >> 20 == ip >> 20 or \
        ip2long("192.168.0.0") >> 16 == ip >> 16 or \
        ip2long("0.0.0.0") >> 24 == ip >> 24


cache_control = {"Cache-Control": "public, immutable"}
forbid_set = set(['Host', 'X-Forwarded-Host', 'X-Forwarded-For', 'X-Forwarded-Proto', 'Alt-Used'])
@app.route('/<path:path>', methods=['GET', 'POST'])
def fetch_image(path):
    # 获取请求中的url参数
    image_url = path
    if not image_url:
        app.logger.warning("no image_url")
        return "Missing URL parameter", 400  # 400 Bad Request响应

    image_url = base64.b64decode(image_url + '==').decode('utf-8')

    # http/https
    if not re.match(r"^https?://.*/.*$", image_url):
        raise BaseException("url format error")

    if image_url.find("https") != 0:
        image_url = image_url.replace("http", "https", 1)
    # 解析URL获取域名
    parsed_url = urlparse(image_url)
    domain_name = extract_main_domain(parsed_url.netloc)

    if domain_name not in config.whitelist:
        app.logger.warning("domain_name not in whitelist: %s", domain_name)
        return "Missing URL parameter", 400  # 400 Bad Request响应

    new_domain_name = config.domains.get(domain_name, parsed_url.netloc)
    app.logger.warning('origin: %s domain_name:%s new_domain_name %s', image_url, domain_name, new_domain_name)
    domain = f'{parsed_url.scheme}://{new_domain_name}'

    # 如果是内网地址，终止访问
    ip_address = socket.getaddrinfo(parsed_url.netloc, 'https')[0][4][0]
    if is_inner_ipaddress(ip_address):
        raise BaseException("inner ip address attack")
   
    # 为请求添加'Referer'头部并获取图片
    headers = {key: value for key, value in request.headers if key not in forbid_set}
    headers['Referer'] = domain
    try:
        response = requests.get(image_url, headers=headers, stream=True, allow_redirects=False)
        # 确保请求成功
        response.raise_for_status()
    except requests.RequestException as e:
        app.logger.warning("request exception: %s", str(e))
        return str(e), 400  # 500 Internal Server Error响应

    # 创建一个streaming response传回原图数据
    return Response(response.iter_content(chunk_size=1024), content_type=response.headers['Content-Type'], headers=cache_control)

if __name__ == '__main__':
    #development
    #app.run(port=7997, debug=False, host='0.0.0.0')  # 启动服务监听在7997端
    from waitress import serve
    serve(app, port=7997, host='0.0.0.0', threads=16) 
