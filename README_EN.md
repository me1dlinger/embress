<div align="center">
 <img width="300" src="./docs/imgs/logo.svg"/>
</div>


<div align="center">

[![中文](https://img.shields.io/badge/中文-README-red)](README.md)
[![English](https://img.shields.io/badge/English-README-blue)](README_EN.md)
<br>
[![Docker](https://img.shields.io/badge/-Docker-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/r/meidlinger1024/embress)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-4CAF50?style=flat-square)](LICENSE)
</div>

---

## 🔰 Overview

**EMBRESS** is a fully automated file renaming tool designed for media libraries such as **Emby**, **Jellyfin**, or **Plex**, ensuring all file names conform to standardized naming conventions for proper scraping and metadata parsing.

---

## 🎗️ Usage Prerequisites

- File Naming Convention​
Ensure your media library follows this structure: [**/data/anime/Series XX/Season 01/AnimeXX 01 [1920x1080].mkv**](https://emby.media/support/articles/TV-Naming.html)

- Docker Volume Mapping​
Map your host's directory to the container, like:
 **-v /data/anime:/app/media/anime**
EMBRESS will automatically detect seasons via Season XX directory names


## 🚀 Features


### 📁 Auto-Renaming

- Scheduled directory scanning
- Automatically apply regex rules for filename rewriting
- Logging for scan and rename operations
- Whitelist support
- To be continued...

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
│   ├── database.py                 ➔ database
│   ├── requirements.txt            ➔ Python dependencies
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
  -v ${conf_path}:/app/conf \
  -e TZ=Asia/Shanghai \
  -e ACCESS_KEY=${ACCESS_KEY} \
  -e MEDIA_PATH=/app/media \
  -e CONFIG_DB_PATH=/app/conf/config.db
  -e LOG_PATH=/app/python/logs
  -e SCAN_INTERVAL=3600 \
  meidlinger1024/embress:latest
```

${media_path1}: Media library directory 1

${media_path2}: Media library directory 2

${logs_path}: Python logs directory, scan record persistence directory

${ACCESS_KEY}: Access key

SCAN_INTERVAL: Scan interval in seconds

MEDIA_PATH: Container media library root directory (default: /app/media)

CONFIG_DB_PATH:database directory, (default: /app/conf/config.db)

LOG_PATH:app-log directory, (default: /app/python/logs)

### Run with Docker Compose
```
version: "3"
services:
  embresse:
    image: embress
    container_name: embress
    restart: always
    ports:
      - "15000:15000"
    volumes:
      - _media_path1:/app/media/path1
      - _media_path2:/app/media/path2
      - _logs_path:/app/python/logs
      - _conf_path:/app/conf
    environment:
      - TZ=Asia/Shanghai
      - ACCESS_KEY=ACCESS_KEY
      - MEDIA_PATH=/app/media
      - CONFIG_DB_PATH=/app/conf/config.db
      - LOG_PATH=/app/python/logs
      - SCAN_INTERVAL=3600
```

## 🧩 Screenshots

<div align="center">
 <img src="./docs/screenshots/1.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/1.5.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/1.6.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/1.7.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/1.8.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/2.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/3.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/4.png"/>
</div>
<div align="center">
 <img src="./docs/screenshots/5.png"/>
</div>