#!/usr/bin/env python3
"""
VPS Control Panel Pro - Enhanced Edition
Advanced server management with persistent terminal sessions
"""

import os
import subprocess
import threading
import time
import json
import shutil
import platform
import psutil
import signal
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template, jsonify, send_file
from flask_socketio import SocketIO, emit
from werkzeug.utils import secure_filename

# Configuration
HOST = "0.0.0.0"
PORT = 8080
UPLOAD_FOLDER = "/tmp/vps_uploads"
MAX_TERMINAL_HISTORY = 1000
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.config["SECRET_KEY"] = "vps_control_pro_2024"
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 500 * 1024 * 1024  # 500MB

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading', ping_timeout=60, ping_interval=25)

# Global state for persistent terminal sessions
terminal_sessions = {}
session_lock = threading.Lock()

class TerminalSession:
    """Persistent terminal session with shell process"""
    def __init__(self, sid):
        self.sid = sid
        self.process = None
        self.cwd = os.path.expanduser("~")
        self.history = []
        self.start_shell()
    
    def start_shell(self):
        """Start a persistent shell process"""
        try:
            self.process = subprocess.Popen(
                ['/bin/bash'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.cwd,
                universal_newlines=True,
                bufsize=0
            )
            
            # Start output readers
            threading.Thread(target=self._read_output, args=('stdout',), daemon=True).start()
            threading.Thread(target=self._read_output, args=('stderr',), daemon=True).start()
            
            print(f"[Terminal] Started session for {self.sid}")
        except Exception as e:
            print(f"[Terminal] Error starting shell: {e}")
    
    def _read_output(self, stream_type):
        """Read output from shell process"""
        stream = self.process.stdout if stream_type == 'stdout' else self.process.stderr
        try:
            while self.process and self.process.poll() is None:
                line = stream.readline()
                if line:
                    self._emit_output(stream_type, line)
        except Exception as e:
            print(f"[Terminal] Error reading {stream_type}: {e}")
    
    def _emit_output(self, stream_type, text):
        """Emit output to client"""
        self.history.append({'type': stream_type, 'text': text, 'time': time.time()})
        if len(self.history) > MAX_TERMINAL_HISTORY:
            self.history = self.history[-MAX_TERMINAL_HISTORY:]
        
        socketio.emit('terminal_output', {
            'stream': stream_type,
            'text': text
        }, room=self.sid)
    
    def execute_command(self, cmd):
        """Execute command in persistent shell"""
        if not self.process or self.process.poll() is not None:
            self.start_shell()
        
        try:
            # Add command to history
            self.history.append({'type': 'command', 'text': cmd, 'time': time.time()})
            
            # Send command to shell
            self.process.stdin.write(cmd + '\n')
            self.process.stdin.flush()
            
            # Emit command echo
            socketio.emit('terminal_output', {
                'stream': 'command',
                'text': f"$ {cmd}\n"
            }, room=self.sid)
            
        except Exception as e:
            error_msg = f"Error executing command: {str(e)}\n"
            self._emit_output('stderr', error_msg)
    
    def change_directory(self, path):
        """Change working directory"""
        try:
            os.chdir(path)
            self.cwd = os.getcwd()
            self.execute_command(f'cd {path}')
            return True
        except Exception as e:
            self._emit_output('stderr', f"Error changing directory: {str(e)}\n")
            return False
    
    def cleanup(self):
        """Clean up terminal session"""
        if self.process:
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except:
                try:
                    self.process.kill()
                except:
                    pass
        print(f"[Terminal] Cleaned up session for {self.sid}")

def get_terminal_session(sid):
    """Get or create terminal session for client"""
    with session_lock:
        if sid not in terminal_sessions:
            terminal_sessions[sid] = TerminalSession(sid)
        return terminal_sessions[sid]

def cleanup_terminal_session(sid):
    """Remove terminal session"""
    with session_lock:
        if sid in terminal_sessions:
            terminal_sessions[sid].cleanup()
            del terminal_sessions[sid]

# Helper Functions
def format_size(bytes_size):
    """Format bytes to human readable size"""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.2f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.2f} PB"

def get_system_stats():
    """Get detailed system statistics"""
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        boot_time = psutil.boot_time()
        uptime = time.time() - boot_time
        
        # Network stats
        net_io = psutil.net_io_counters()
        
        # Process count
        process_count = len(psutil.pids())
        
        stats = {
            'cpu_percent': cpu_percent,
            'cpu_count': psutil.cpu_count(),
            'memory_percent': memory.percent,
            'memory_used': format_size(memory.used),
            'memory_total': format_size(memory.total),
            'disk_percent': disk.percent,
            'disk_used': format_size(disk.used),
            'disk_total': format_size(disk.total),
            'uptime_days': int(uptime // 86400),
            'uptime_hours': int((uptime % 86400) // 3600),
            'uptime_minutes': int((uptime % 3600) // 60),
            'network_sent': format_size(net_io.bytes_sent),
            'network_recv': format_size(net_io.bytes_recv),
            'process_count': process_count,
            'load_avg': os.getloadavg() if hasattr(os, 'getloadavg') else [0, 0, 0],
            'os': f"{platform.system()} {platform.release()}",
            'hostname': platform.node()
        }
        return stats
    except Exception as e:
        print(f"Error getting system stats: {e}")
        return None

def get_process_list():
    """Get list of running processes"""
    try:
        processes = []
        for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent', 'status']):
            try:
                processes.append(proc.info)
            except:
                pass
        return sorted(processes, key=lambda x: x.get('memory_percent', 0), reverse=True)[:50]
    except Exception as e:
        print(f"Error getting process list: {e}")
        return []

# Routes
@app.route("/")
def index():
    """Serve main HTML interface"""
    return render_template('all.html')

@app.route("/api/files", methods=["POST"])
def api_files():
    """List files in directory"""
    try:
        data = request.get_json()
        path = data.get("path", os.path.expanduser("~"))
        
        if not os.path.exists(path):
            return jsonify({"success": False, "error": "Path does not exist"})
        
        if not os.path.isdir(path):
            return jsonify({"success": False, "error": "Not a directory"})
        
        items = []
        for item in os.listdir(path):
            item_path = os.path.join(path, item)
            try:
                stat = os.stat(item_path)
                is_dir = os.path.isdir(item_path)
                
                items.append({
                    "name": item,
                    "path": item_path,
                    "is_dir": is_dir,
                    "size": format_size(stat.st_size) if not is_dir else "—",
                    "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "permissions": oct(stat.st_mode)[-3:]
                })
            except Exception as e:
                print(f"Error processing {item}: {e}")
                continue
        
        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
        return jsonify({"success": True, "files": items, "current_path": path})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/create", methods=["POST"])
def api_create():
    """Create file or folder"""
    try:
        data = request.get_json()
        path = data.get("path")
        item_type = data.get("type")
        content = data.get("content", "")
        
        if item_type == "folder":
            os.makedirs(path, exist_ok=True)
        else:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        
        return jsonify({"success": True, "message": f"Created {item_type} successfully"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/read", methods=["POST"])
def api_read():
    """Read file content"""
    try:
        data = request.get_json()
        path = data.get("path")
        
        # Check file size
        size = os.path.getsize(path)
        if size > 10 * 1024 * 1024:  # 10MB limit
            return jsonify({"success": False, "error": "File too large to edit (>10MB)"})
        
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        
        return jsonify({"success": True, "content": content, "size": format_size(size)})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/write", methods=["POST"])
def api_write():
    """Write file content"""
    try:
        data = request.get_json()
        path = data.get("path")
        content = data.get("content")
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        
        return jsonify({"success": True, "message": "File saved successfully"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/delete", methods=["POST"])
def api_delete():
    """Delete file or folder"""
    try:
        data = request.get_json()
        path = data.get("path")
        
        if os.path.isdir(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        
        return jsonify({"success": True, "message": "Deleted successfully"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/upload", methods=["POST"])
def api_upload():
    """Upload file"""
    try:
        if 'file' not in request.files:
            return jsonify({"success": False, "error": "No file provided"})
        
        file = request.files['file']
        target_path = request.form.get('path', os.path.expanduser("~"))
        
        if file.filename == '':
            return jsonify({"success": False, "error": "Empty filename"})
        
        filename = secure_filename(file.filename)
        filepath = os.path.join(target_path, filename)
        file.save(filepath)
        
        return jsonify({"success": True, "message": f"Uploaded {filename}"})
    
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/download/<path:filepath>")
def api_download(filepath):
    """Download file"""
    try:
        return send_file(filepath, as_attachment=True)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 404

@app.route("/api/sysinfo", methods=["GET"])
def api_sysinfo():
    """Get system information"""
    try:
        stats = get_system_stats()
        if stats:
            return jsonify({"success": True, "stats": stats})
        else:
            return jsonify({"success": False, "error": "Could not retrieve stats"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/processes", methods=["GET"])
def api_processes():
    """Get running processes"""
    try:
        processes = get_process_list()
        return jsonify({"success": True, "processes": processes})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

@app.route("/api/kill_process", methods=["POST"])
def api_kill_process():
    """Kill a process"""
    try:
        data = request.get_json()
        pid = data.get("pid")
        
        os.kill(pid, signal.SIGTERM)
        return jsonify({"success": True, "message": f"Killed process {pid}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

# WebSocket Events
@socketio.on('connect')
def handle_connect():
    """Handle client connection"""
    print(f"[WebSocket] Client connected: {request.sid}")
    get_terminal_session(request.sid)
    emit('connected', {'message': 'Terminal session ready'})

@socketio.on('disconnect')
def handle_disconnect():
    """Handle client disconnection"""
    print(f"[WebSocket] Client disconnected: {request.sid}")
    cleanup_terminal_session(request.sid)

@socketio.on('terminal_command')
def handle_terminal_command(data):
    """Handle terminal command"""
    cmd = data.get('cmd', '').strip()
    if not cmd:
        return
    
    session = get_terminal_session(request.sid)
    
    # Handle special commands
    if cmd.startswith('cd '):
        path = cmd[3:].strip()
        session.change_directory(path)
    else:
        session.execute_command(cmd)

@socketio.on('terminal_resize')
def handle_terminal_resize(data):
    """Handle terminal resize"""
    rows = data.get('rows', 24)
    cols = data.get('cols', 80)
    # Terminal resize handling can be implemented here

@socketio.on('request_history')
def handle_request_history():
    """Send terminal history to client"""
    session = get_terminal_session(request.sid)
    emit('terminal_history', {'history': session.history})

# Run Server
if __name__ == "__main__":
    print("=" * 70)
    print("🚀 VPS Control Panel Pro - Enhanced Edition")
    print("=" * 70)
    print(f"📡 Server URL: http://{HOST}:{PORT}")
    print(f"📁 Upload Folder: {UPLOAD_FOLDER}")
    print(f"💻 System: {platform.system()} {platform.release()}")
    print(f"🖥️  Hostname: {platform.node()}")
    print("=" * 70)
    print("✨ Features:")
    print("   • Persistent terminal sessions")
    print("   • Real-time system monitoring")
    print("   • Advanced file management")
    print("   • Process management")
    print("=" * 70)
    
    socketio.run(app, host=HOST, port=PORT, debug=False, allow_unsafe_werkzeug=True)
