# EMBRESS

<div align="center">

[![English](https://img.shields.io/badge/English-README-blue)](README_EN.md)
[![中文](https://img.shields.io/badge/中文-README-red)](README.md)
<br>
[![Docker](https://img.shields.io/badge/-Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/meidlinger1024/embress)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-4CAF50?style=flat-square)](LICENSE)
</div>

---

## 🔰 Overview

**EMBRESS** is a fully automated file renaming tool designed for media libraries such as **Emby**, **Jellyfin**, or **Plex**, ensuring all file names conform to standardized naming conventions for proper scraping and metadata parsing.

---

## 🚀 Features



### 📁 Auto-Renaming

- Scheduled directory scanning
- Automatically apply regex rules for filename rewriting
- Logging for scan and rename operations

### 📊 Web Dashboard

- System configuration overview
- Manual or targeted scan triggering
- Scan history records
- Rename history tracking
- Log viewer

### 🔐 Access Control

- Optional access key for UI protection

### 📁 Project Structure

```
embress
├── python
│   │ 
│   ├── app.py                      ➔ API server
│   ├── embress_rename.py           ➔ rename logic
│   ├── requirements.txt            ➔ Python dependencies
│   ├── conf
│   │   └── regex_patterns.json     ➔ Regex config file
│   ├── templates
│   │   └── index.html              ➔ Dashboard UI
│   └── static                      ➔ Static resources
│        ├── css
│        │   └── styles.css 
│        └── js
│            ├── main.js
│            └── vue.js
│     
│     
├── conf
│   └── supervisord.conf            ➔ Supervisor config
├── Dockerfile                      ➔ Docker build file
└── docker-compose.yml              ➔ Compose file
  
```

## 🐳 Deployment Guide

### Pull Docker Image

```
docker pull meidlinger1024/embress:latest
```

### Run with Docker

```

docker run -d \
  --name embress \
  -p 15000:15000 \
  -v ${media_path1}:/app/media/path1 \
  -v ${media_path2}:/app/media/path2 \
  -v ${logs_path}:/app/python/logs \
  -v ${conf_path}/regex_patterns.json:/app/python/conf/regex_patterns.json \
  -e TZ=Asia/Shanghai \
  -e ACCESS_KEY=${ACCESS_KEY} \
  -e MEDIA_PATH=/app/media \
  -e REGEX_PATH=/app/python/conf/regex_patterns.json \
  -e SCAN_INTERVAL=3600 \
  embress:latest
```

### Run with Docker Compose
```
version: '3'
services:
  embress:
    image: embress:latest
    container_name: embress
    restart: always
    ports:
      - "15000:15000"
    volumes:
      - ${media_path1}:/app/media/path1
      - ${media_path2}:/app/media/path2
      - ${logs_path}:/app/python/logs
      - ${conf_path}/regex_patterns.json:/app/python/conf/regex_patterns.json
    environment:
      - TZ=Asia/Shanghai
      - ACCESS_KEY=${ACCESS_KEY}
      - MEDIA_PATH=/app/media
      - REGEX_PATH=/app/python/conf/regex_patterns.json
      - SCAN_INTERVAL=3600
```

## 🧩 界面截图

![1](screenshots/1.png)

![2](screenshots/2.png)

![3](screenshots/3.png)

![4](screenshots/4.png)

![5](screenshots/5.png)


