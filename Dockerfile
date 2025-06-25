FROM python:3.9-slim

# 在 sources.list 中补全 security 源
RUN echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bullseye main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
  echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bullseye-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
  echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian/ bullseye-backports main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
  echo "deb https://mirrors.tuna.tsinghua.edu.cn/debian-security bullseye-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

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

# 复制脚本和API文件
COPY /python /app/python
COPY conf/supervisord.conf /etc/supervisor/conf.d/supervisord.conf
RUN chmod +x /app/python/app.py
RUN chmod +x /app/python/emby_renamer.py

RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

RUN pip install --no-cache-dir -r /app/python/requirements.txt

EXPOSE 15000

# 启动命令
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]