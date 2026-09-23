<div align="center">
 <img width="300" src="./docs/imgs/logo.svg"/>
</div>


<div align="center">

[![中文](https://img.shields.io/badge/中文-README-red)](README.md)
[![English](https://img.shields.io/badge/English-README-blue)](README_EN.md)
<br>
[![Docker](https://img.shields.io/docker/pulls/meidlinger1024/embress?logo=docker)](https://hub.docker.com/r/meidlinger1024/embress)
[![License: GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-4CAF50?style=flat-square)](LICENSE)
</div>

---

## Overview

**EMBRESS** is a fully automated file renaming tool designed for media libraries such as **Emby**, **Jellyfin**, or **Plex**, ensuring all file names conform to standardized naming conventions for proper scraping and metadata parsing.

---

## Usage Prerequisites

- File Naming Convention​
Ensure your media library follows this structure: [**/data/anime/Series XX/Season 01/AnimeXX 01 [1920x1080].mkv**](https://emby.media/support/articles/TV-Naming.html)

- Docker Volume Mapping​
Map your host's directory to the container, like:
 **-v /data/anime:/app/media/anime**
EMBRESS will automatically detect seasons via Season XX directory names


## Features


### Auto-Renaming

- Scheduled directory scanning, seasons detected via Season XX directory names
- Automatically apply regex rules for filename rewriting
- Online regex debugger
- Logging for scan and rename operations
- Whitelist support, matching files/directories are skipped

### AI Renaming

For messy filenames that regex rules cannot cover, using an LLM (OpenAI-compatible API).

How to use:

1. Open "AI Providers", add a provider (name, model, Base URL, API Key), click "Test" to verify, and optionally "Set as default". API keys are stored encrypted
2. Open "AI Rename", pick the provider, enter the directory to be handled by AI (relative to the media root, e.g. `Anime/Show`), and click "Bind"
3. On the next manual or scheduled scan, files under bound directories are renamed by AI; results are listed in "Change Records"

Effects:

- Detects show name, season and episode, and outputs Emby-compliant names: `Show - SxxEyy - Episode Title.ext`
- Reuses previous rename records of the same show as samples to keep naming consistent
- Keeps quality, source and fansub tags from the original filename
- Works with the regex flow: regex runs first, AI handles what is left; unrecognizable files are skipped instead of being mis-renamed
- Multiple bindings supported (longest prefix wins); bindings can be enabled/disabled/removed anytime

### Auto Organizing

Automatically files scattered episodes into the standard `MediaType/Show/Season XX` structure, with no manual work.

How to use:

1. In the "AI Rename" window, enable the "Auto Organizing" switch, choose the model and set the interval (60-86400 seconds)
2. Click "Run Now", or wait for the scheduled run. The "Pending Files" list previews what will be processed; "Re-evaluate" makes deferred files eligible again
3. After a run, open the result dialog: "View Process" expands a timeline of AI reasoning and program steps; "Changes & Restore" allows one-click restore by show / season / single file

Effects:

- Creates `MediaType/Show/Season XX` directories and moves files in; subtitles, audio, images and NFO are moved together
- English or romaji titles (e.g. `Food Court de, Mata Ashita`) are resolved to the official Chinese title
- The AI only decides the target; directory creation, moving, renaming and cleanup are all done by the program
- Files are never overwritten: an existing target is skipped
- Unrecognizable files are retried automatically without wasting tokens; the cache is reset when the prompt or model changes
- Results are recorded in "Change Records" with an "AI Organizing" tag, and marked "Restored" after a restore

> Prompts live in separate files (`python/prompts/`); restart the container after editing.

### Web Dashboard

- System configuration overview, scan and organizing status
- Manual or targeted scan triggering
- Whitelist and regex rule configuration
- Restore renamed files by path
- Scan history records
- Change records (with source tags for AI renaming / organizing, and restore status)
- Log viewer

### Access Control

- Optional access key for UI protection

## Project Structure

```
embress
├── python
│   ├── app.py                      ➔ API server and web routes
│   ├── embress_renamer.py          ➔ Scanning and regex-based renaming
│   ├── ai_renamer.py               ➔ AI renaming and model providers
│   ├── ai_organizer.py             ➔ Auto organizing and restore
│   ├── prompt_loader.py            ➔ System prompt loader
│   ├── prompts                     ➔ System prompts (separate files, customizable)
│   │   ├── rename_system.txt       ➔ AI renaming prompt
│   │   ├── organize_system.txt     ➔ Auto organizing prompt
│   │   └── connectivity_probe.txt  ➔ Connectivity test prompt
│   ├── database.py                 ➔ Database
│   ├── crypto_utils.py             ➔ Encrypted API key storage
│   ├── email_notifier.py           ➔ Email notifications
│   ├── logging_utils.py            ➔ Logging setup
│   ├── requirements.txt            ➔ Python dependencies
│   ├── templates
│   │   └── index.html              ➔ Dashboard UI
│   └── static                      ➔ Static resources
│        ├── css                    ➔ Styles (app.css / theme.css)
│        ├── img                    ➔ Icon assets
│        └── js
│            └── main.js            ➔ Frontend logic
├── docs
│   ├── imgs                        ➔ Project logo
│   └── screenshots                 ➔ Screenshots
├── conf
│   ├── supervisord.conf            ➔ Supervisor config
│   └── regex_pattern.json          ➔ Default regex config
├── Dockerfile                      ➔ Docker build file
└── docker-compose.yml              ➔ Compose file
  
```

## Deployment Guide

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
  -e CONFIG_DB_PATH=/app/conf/config.db \
  -e DEFAULT_REGEX_PATH=/app/conf/regex_pattern.json \
  -e LOG_PATH=/app/python/logs \
  -e SCAN_INTERVAL=3600 \
  -e EMAIL_ENABLED=false \
  -e EMAIL_HOST=mail.163.com \
  -e EMAIL_PORT=465 \
  -e EMAIL_USER=from@mail.com \
  -e EMAIL_PASSWORD=password \
  -e EMAIL_RECIPIENTS=to@mail.com \
  -e AI_BASE_URL=https://api.openai.com/v1 \
  -e AI_API_KEY=${AI_API_KEY} \
  -e AI_MODEL=gpt-4o-mini \
  -e AUTO_ORGANIZE_INTERVAL=3600 \
  meidlinger1024/embress:latest
```

${media_path1}: Media library directory 1

${media_path2}: Media library directory 2

${logs_path}: Python logs directory, scan record persistence directory

${ACCESS_KEY}: Access key

SCAN_INTERVAL: Scan interval in seconds

MEDIA_PATH: Container media library root directory (default: /app/media)

CONFIG_DB_PATH: Database directory, (default: /app/conf/config.db)

LOG_PATH: app-log directory, (default: /app/python/logs)

EMAIL_ENABLED: Email notification, (default: false)

AI_BASE_URL: AI endpoint (OpenAI-compatible), (default: https://api.openai.com/v1)

AI_API_KEY: AI API key. It can also be added in the web UI under "AI Providers" (recommended, stored encrypted)

AI_MODEL: Default model name, (default: gpt-4o-mini)

AI_TIMEOUT: AI request timeout in seconds, (default: 60)

AI_MAX_FILES: Max files sent to the AI per request, (default: 80)

AUTO_ORGANIZE_INTERVAL: Default auto-organizing interval in seconds, (default: 3600)

AUTO_ORGANIZE_TTL: How long (seconds) unrecognizable files stay deferred before being re-evaluated, (default: 86400)

EMBRESS_SECRET_KEY / EMBRESS_KEY_PATH: Key used to encrypt stored API keys; persist the conf directory or set explicitly

### Run with Docker Compose
```
version: "3"
services:
  embress:
    image: meidlinger1024/embress:latest
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
      - DEFAULT_REGEX_PATH=/app/conf/regex_pattern.json
      - LOG_PATH=/app/python/logs
      - SCAN_INTERVAL=3600
      - EMAIL_ENABLED=false
      - EMAIL_HOST=mail.163.com
      - EMAIL_PORT=465
      - EMAIL_USER=from@mail.com
      - EMAIL_PASSWORD=password
      - EMAIL_RECIPIENTS=to@mail.com
      - AI_BASE_URL=https://api.openai.com/v1
      - AI_API_KEY=AI_API_KEY
      - AI_MODEL=gpt-4o-mini
      - AUTO_ORGANIZE_INTERVAL=3600
```

## Screenshots

<div align="center">
 <img src="./docs/screenshots/1.png"/>
 <p>Dashboard</p>
</div>
<div align="center">
 <img src="./docs/screenshots/2.png"/>
 <p>Unrenamed Files</p>
</div>
<div align="center">
 <img src="./docs/screenshots/3.png"/>
 <p>Targeted Scan</p>
</div>
<div align="center">
 <img src="./docs/screenshots/4.png"/>
 <p>Whitelist</p>
</div>
<div align="center">
 <img src="./docs/screenshots/5.png"/>
 <p>Regex Rules</p>
</div>
<div align="center">
 <img src="./docs/screenshots/6.png"/>
 <p>Regex Debugger</p>
</div>
<div align="center">
 <img src="./docs/screenshots/7.png"/>
 <p>AI Providers</p>
</div>
<div align="center">
 <img src="./docs/screenshots/8.png"/>
 <p>Add Provider</p>
</div>
<div align="center">
 <img src="./docs/screenshots/9.png"/>
 <p>AI Rename</p>
</div>
<div align="center">
 <img src="./docs/screenshots/10.png"/>
 <p>Organize Timeline</p>
</div>
<div align="center">
 <img src="./docs/screenshots/11.png"/>
 <p>Scan History</p>
</div>
<div align="center">
 <img src="./docs/screenshots/12.png"/>
 <p>Change Records</p>
</div>
<div align="center">
 <img src="./docs/screenshots/13.png"/>
 <p>Organize Restore</p>
</div>
<div align="center">
 <img src="./docs/screenshots/14.png"/>
 <p>Rename Records</p>
</div>
<div align="center">
 <img src="./docs/screenshots/15.png"/>
 <p>Log Viewer</p>
</div>
