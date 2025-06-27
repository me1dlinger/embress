# EMBRESS

<div align="center">

[![English](https://img.shields.io/badge/English-README-blue)](README_EN.md)
[![中文](https://img.shields.io/badge/中文-README-red)](README.md)
<br>
[![Docker](https://img.shields.io/badge/-Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/meidlinger1024/embress)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-4CAF50?style=flat-square)](LICENSE)
</div>


**EMBRESS**是一个全自动的文件重命名工具，专为**Emby**、**Jellyfin**、**Plex**等媒体库设计，可确保所有文件名称符合标准化的命名约定，以进行适当的刮擦和元数据解析。

## 🎗️ 用前提示

请确保影视库中节目目录命名已经符合规范，如 [**/data/anime/节目XX/Season 01/AnimeXX 01 [1920x1080].mkv**](https://emby.media/support/articles/TV-Naming.html)

可通过将**/data/anime**映射到docker容器内目录

如 **-v /data/anime:/app/media/anime**

EMBRESS会自动将宿主机anime目录添加到影视库的遍历列表中，通过Season XX目录名，以识别出季度信息

## 🔰 功能说明


### 文件自动重命名

自动扫描配置的目录
多种正则替换规则自动应用
扫描日志记录

### 页面展示

仪表盘展示系统配置
提供手动全部扫描和指定路径扫描
扫描历史展示
文件变更记录展示
查看日志


### 页面访问鉴权

可配置访问密钥

### 文件结构

```
embress
├── python
│   │ 
│   ├── app.py                      ➔ API服务
│   ├── embress_rename.py           ➔ 重命名业务
│   ├── requirements.txt            ➔ python依赖
│   ├── conf
│   │   └── regex_patterns.json     ➔ 正则配置
│   ├── templates
│   │   └── index.html              ➔ 前端面板
│   └── static                      ➔ 静态文件目录
│        ├── css
│        │   └── styles.css
│        └── js
│            ├── main.js
│            └── vue.js
│     
│     
├── conf
│   └── supervisord.conf            ➔ supervisord进程配置
├── Dockerfile                      ➔ 打包配置
└── docker-compose.yml              ➔ docker构建配置，宿主机要先创建对应目录
  
```

## 🐳 部署说明


### 拉取镜像

```
docker pull meidlinger1024/embress:latest
```
### docker run配置

```

docker run -d \
  --name embress \
  -p 15000:15000 \
  -v ${media_path1}:/app/media/path1 \
  -v ${media_path2}:/app/media/path2 \
  -v ${logs_path}:/app/python/logs \
  -e TZ=Asia/Shanghai \
  -e ACCESS_KEY=${ACCESS_KEY} \
  -e MEDIA_PATH=/app/media \
  -e REGEX_PATH=/app/python/conf/regex_patterns.json \
  -e WHITELIST_PATH=/app/python/conf/whitelist.json \
  -e SCAN_INTERVAL=3600 \
  embress:latest
```

${media_path1}：影视库目录1

${media_path2}：影视库目录2

${logs_path}：python日志目录，扫描记录持久化目录

${ACCESS_KEY}：访问秘钥

SCAN_INTERVAL：扫描间隔，单位秒

MEDIA_PATH:容器影视库根目录，默认是/app/media

REGEX_PATH:程序正则配置地址，默认/app/python/conf/regex_patterns.json

WHITELIST_PATH：程序文件名白名单配置地址，默认/app/python/conf/whitelist.json

### docker-compose配置
```
version: '3'
services:
  embress:
    image: embress:1.0.0
    container_name: embress
    restart: always
    ports:
      - "15000:15000"
    volumes:
      - ${media_path1}:/app/media/path1
      - ${media_path2}:/app/media/path2
      - ${logs_path}:/app/python/logs
    environment:
      - TZ=Asia/Shanghai
      - ACCESS_KEY=${ACCESS_KEY}
      - MEDIA_PATH=/app/media
      - REGEX_PATH=/app/python/conf/regex_patterns.json
      - WHITELIST_PATH=/app/python/conf/whitelist.json
      - SCAN_INTERVAL=3600
```

## 🧩 界面截图

![1](screenshots/1.png)

![1.5](screenshots/1.5.png)

![1.6](screenshots/1.6.png)

![1.7](screenshots/1.7.png)

![1.8](screenshots/1.8.png)

![2](screenshots/2.png)

![3](screenshots/3.png)

![4](screenshots/4.png)

![5](screenshots/5.png)


