FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai \
    PYTHONPATH=/app

WORKDIR /app

# 安装基础运行依赖与时区
RUN apt-get update && apt-get install -y --no-install-recommends \
    tzdata \
    procps \
    curl \
    ca-certificates \
    openssh-client \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && echo Asia/Shanghai > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt

COPY app/ ./app/

CMD ["python", "-u", "app/main.py"]
