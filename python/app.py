"""
/**
 * @author: Meidlinger
 * @date: 2025-06-24
 */
"""
import os
import json
import logging
from pathlib import Path
from datetime import datetime
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from emby_renamer import EmbyRenamer
from threading import Lock

app = Flask(__name__)

# 配置
MEDIA_PATH = os.getenv('MEDIA_PATH', '/app/media')
ACCESS_KEY = os.getenv('ACCESS_KEY', '12345')
SCAN_INTERVAL = int(os.getenv('SCAN_INTERVAL', 3600)) 
DATA_DIR      = Path(os.getenv('DATA_DIR', '/app/data'))
HISTORY_FILE  = DATA_DIR / 'scan_history.json'
DATA_DIR.mkdir(parents=True, exist_ok=True)
# 全局变量
renamer = EmbyRenamer(MEDIA_PATH)
scheduler = BackgroundScheduler()
last_scan_result = None
# === 全局状态 ===
history_lock = Lock()         
scan_history = []   

def load_history():
    global scan_history, last_scan_result
    if HISTORY_FILE.exists():
        with HISTORY_FILE.open('r', encoding='utf-8') as f:
            payload = json.load(f)
        scan_history     = payload.get('history', [])
        last_scan_result = payload.get('last_scan')
def persist_history():
    """把 scan_history 和 last_scan_result 落地到 JSON 文件"""
    with history_lock:
        with HISTORY_FILE.open('w', encoding='utf-8') as f:
            json.dump({
                'history' : scan_history,
                'last_scan': last_scan_result
            }, f, ensure_ascii=False, indent=2)
def scheduled_scan():
    """定时扫描任务"""
    global last_scan_result, scan_history
    
    try:
        app.logger.info("开始定时扫描...")
        result = renamer.scan_and_rename()
        last_scan_result = result
        
        # 保存到历史记录
        scan_history.append(result)
        # 只保留最近50次记录
        scan_history = scan_history[-50:]
        
        app.logger.info(f"定时扫描完成: {result}")
        
    except Exception as e:
        app.logger.error(f"定时扫描失败: {e}")
        last_scan_result = {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }

@app.route('/')
def index():
    """主页"""
    return render_template('index.html')

@app.route('/api/auth', methods=['POST'])
def authenticate():
    """验证访问密钥"""
    data = request.get_json()
    if not data or 'access_key' not in data:
        return jsonify({'success': False, 'message': '缺少访问密钥'})
    
    if data['access_key'] == ACCESS_KEY:
        return jsonify({'success': True, 'message': '验证成功'})
    else:
        return jsonify({'success': False, 'message': '访问密钥错误'})

@app.route('/api/status')
def get_status():
    """获取系统状态"""
    return jsonify({
        'media_path': MEDIA_PATH,
        'scan_interval': SCAN_INTERVAL,
        'last_scan': last_scan_result,
        'scheduler_running': scheduler.running,
        'total_scans': len(scan_history)
    })

@app.route('/api/history')
def get_history():
    """获取扫描历史"""
    return jsonify({
        'history': scan_history,
        'total': len(scan_history)
    })

@app.route('/api/manual-scan', methods=['POST'])
def manual_scan():
    """手动触发扫描"""
    global last_scan_result, scan_history
    
    try:
        app.logger.info("开始手动扫描...")
        result = renamer.scan_and_rename()
        last_scan_result = result
        scan_history.append(result)
        scan_history = scan_history[-50:]
        
        return jsonify({
            'success': True,
            'result': result
        })
        
    except Exception as e:
        app.logger.error(f"手动扫描失败: {e}")
        error_result = {
            'status': 'error',
            'message': str(e),
            'timestamp': datetime.now().isoformat()
        }
        last_scan_result = error_result
        return jsonify({
            'success': False,
            'result': error_result
        })

@app.route('/api/logs')
def get_logs():
    """获取日志文件列表"""
    log_dir = Path('/app/logs')
    if not log_dir.exists():
        return jsonify({'logs': []})
    
    logs = []
    for log_file in sorted(log_dir.glob('*.log'), reverse=True):
        stat = log_file.stat()
        logs.append({
            'name': log_file.name,
            'size': stat.st_size,
            'modified': datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    
    return jsonify({'logs': logs})

@app.route('/api/logs/<filename>')
def get_log_content(filename):
    """获取日志文件内容"""
    log_dir = Path('/app/logs')
    log_file = log_dir / filename
    
    if not log_file.exists() or not filename.endswith('.log'):
        return jsonify({'error': '日志文件不存在'}), 404
    
    try:
        # 读取最后1000行
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            content = ''.join(lines[-1000:])
        
        return jsonify({
            'filename': filename,
            'content': content,
            'total_lines': len(lines)
        })
        
    except Exception as e:
        return jsonify({'error': f'读取日志失败: {e}'}), 500

@app.route('/api/change-records')
def get_change_records():
    """获取所有变更记录"""
    records = []
    media_path = Path(MEDIA_PATH)
    
    if not media_path.exists():
        return jsonify({'records': []})
    
    for show_dir in media_path.iterdir():
        if not show_dir.is_dir():
            continue
            
        for season_dir in show_dir.iterdir():
            if not season_dir.is_dir():
                continue
                
            record_file = season_dir / 'rename_record.json'
            if record_file.exists():
                try:
                    with open(record_file, 'r', encoding='utf-8') as f:
                        season_records = json.load(f)
                    
                    for record in season_records:
                        record['show'] = show_dir.name
                        record['season'] = season_dir.name
                        records.append(record)
                        
                except Exception as e:
                    app.logger.error(f"读取变更记录失败 {record_file}: {e}")
    
    # 按时间排序
    records.sort(key=lambda x: x.get('timestamp', ''), reverse=True)
    
    return jsonify({
        'records': records[:200],  # 返回最新的200条记录
        'total': len(records)
    })

def setup_logging():
    """设置Flask应用日志"""
    if not app.debug:
        log_dir = Path('/app/logs')
        log_dir.mkdir(exist_ok=True)
        
        file_handler = logging.FileHandler(
            log_dir / 'app.log',
            encoding='utf-8'
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        ))
        
        app.logger.addHandler(file_handler)
        app.logger.setLevel(logging.INFO)

if __name__ == '__main__':
    setup_logging()
    
    # 定时任务
    if not scheduler.running:
        scheduler.add_job(
            func=scheduled_scan,
            trigger="interval",
            seconds=SCAN_INTERVAL,
            id='scan_job',
            name='Emby文件扫描任务',
            replace_existing=True
        )
        scheduler.start()
        app.logger.info(f"定时任务已启动，扫描间隔: {SCAN_INTERVAL}秒")

    port = int(os.getenv('FLASK_PORT', 15000))
    app.run(host='0.0.0.0', port=port, debug=False)