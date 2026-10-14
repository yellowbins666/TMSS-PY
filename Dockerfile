FROM python:3.11-slim

# 设置无缓冲输出及工作目录
ENV PYTHONUNBUFFERED=1
WORKDIR /app

# 安装必要的系统证书与网络工具
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY app.py .

# 暴露服务端口（默认为 8080）
EXPOSE 8080

# 运行主程序
CMD ["python", "app.py"]
