FROM python:3.9-slim

# 将基础镜像自带的 Debian 源替换为清华镜像
# 不写死发行版代号（bullseye/bookworm 均可），也不改动组件列表，
# 同时兼容传统 /etc/apt/sources.list 与 bookworm 的 deb822 格式
RUN set -eux; \
  for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources; do \
    if [ -f "$f" ]; then \
      sed -i \
        -e 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        -e 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
        "$f"; \
    fi; \
  done

# 安装依赖
RUN apt-get update && apt-get install -y \
  supervisor  \
  && rm -rf /var/lib/apt/lists/*

# 设置时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime

# 创建目录结构
RUN mkdir -p /app/python
RUN mkdir -p /app/media
RUN mkdir -p /app/conf

# 复制脚本和API文件
COPY /python /app/python
COPY conf/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY conf/regex_pattern.json /app/conf/regex_pattern.json

RUN chmod +x /app/python/app.py
RUN chmod +x /app/python/embress_renamer.py
RUN chmod +x /app/python/database.py
RUN chmod +x /app/python/logging_utils.py

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN pip install --no-cache-dir -r /app/python/requirements.txt

EXPOSE 15000

# 启动命令
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]