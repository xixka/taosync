"""
taoSync 前台服务入口（运行在 :pythonservice 进程）。

业务程序（Tornado 8023）在此进程运行，作为前台服务，避免主进程
（PythonActivity）被 ColorOS 冻结后 8023 不可访问。

p4a 的 PythonService 运行在独立进程，sys.path 与工作目录需显式设置。
"""
import os
import sys
import time
import logging
import threading
import asyncio
import warnings

warnings.filterwarnings('ignore', message='.*character detection dependency.*')

# ======================================================================
# 路径设置：服务进程需显式将 app 目录加入 sys.path
# ======================================================================
_app_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _app_dir not in sys.path:
    sys.path.insert(0, _app_dir)
os.chdir(_app_dir)
os.makedirs('data', exist_ok=True)
os.makedirs('data/log', exist_ok=True)

# ======================================================================
# 内存日志缓冲
# ======================================================================
LOG_MAX = 500
_log_lock = threading.Lock()
_log_entries = []
_log_seq = 0


def _append_log(level, msg):
    global _log_seq
    msg = msg.rstrip('\n')
    if not msg:
        return
    with _log_lock:
        _log_seq += 1
        _log_entries.append({
            'seq': _log_seq,
            'ts': time.time(),
            'level': level,
            'msg': msg,
        })
        if len(_log_entries) > LOG_MAX:
            del _log_entries[:len(_log_entries) - LOG_MAX // 2]
    if _file_fp:
        try:
            _file_fp.write(f'[{level}] {msg}\n')
            _file_fp.flush()
        except Exception:
            pass


def _file_log(level, msg):
    msg = msg.rstrip('\n')
    if not msg:
        return
    if _file_fp:
        try:
            _file_fp.write(f'[{level}] {msg}\n')
            _file_fp.flush()
        except Exception:
            pass


class MemoryLogHandler(logging.Handler):
    def emit(self, record):
        _append_log(record.levelname, record.getMessage())


class _StdoutCapture:
    def __init__(self, level):
        self._level = level
        self._buf = ''

    def write(self, text):
        self._buf += text
        while '\n' in self._buf:
            line, self._buf = self._buf.split('\n', 1)
            if line.strip():
                _append_log(self._level, line)

    def flush(self):
        if self._buf.strip():
            _append_log(self._level, self._buf)
        self._buf = ''


# ======================================================================
# 文件日志后备
# ======================================================================
_file_fp = None
for _log_path in ['/storage/emulated/0/Documents/taosync_debug.log',
                  '/sdcard/Documents/taosync_debug.log',
                  os.path.join(os.getcwd(), 'debug.log')]:
    try:
        _file_fp = open(_log_path, 'a', buffering=1)
        break
    except Exception:
        pass


class _FileLogHandler(logging.Handler):
    def emit(self, record):
        if _file_fp:
            try:
                _file_fp.write(f'[{record.levelname}] {record.getMessage()}\n')
            except Exception:
                pass


# ======================================================================
# 安装日志收集
# ======================================================================
_file_log('INFO', '=== taoSync 服务进程启动 ===')
_file_log('INFO', f'Python: {sys.version}')
_file_log('INFO', f'app_dir: {_app_dir}')
_file_log('INFO', f'cwd: {os.getcwd()}')

_logger = logging.getLogger()
_logger.addHandler(MemoryLogHandler())
_logger.addHandler(_FileLogHandler())

logging.getLogger('tornado.access').setLevel(logging.WARNING)

sys.stdout = _StdoutCapture('INFO')
sys.stderr = _StdoutCapture('ERROR')


def _safe_exit(code=0):
    _append_log('CRITICAL', f'服务进程退出 (code={code})')
    if _file_fp:
        try:
            _file_fp.flush()
        except Exception:
            pass
    os._exit(code)


sys.exit = _safe_exit


def _excepthook(exc_type, exc_value, exc_tb):
    import traceback
    tb = ''.join(traceback.format_exception(exc_type, exc_value, exc_tb))
    _append_log('ERROR', f'未捕获异常:\n{tb}')
    if _file_fp:
        try:
            _file_fp.write(tb)
            _file_fp.flush()
        except Exception:
            pass


sys.excepthook = _excepthook


# ======================================================================
# 业务模块导入
# ======================================================================
from tornado.web import Application, RequestHandler, StaticFileHandler

from common.config import getConfig
from controller import systemController, jobController, notifyController
from service.system import onStart


# ======================================================================
# 日志页面
# ======================================================================
_LOG_PAGE_HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>taoSync 日志</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
html, body { height: 100%; overflow: hidden; }
body {
  background: #1e1e1e;
  color: #d4d4d4;
  font-family: 'Courier New', Consolas, monospace;
  font-size: 12px;
  display: flex;
  flex-direction: column;
}
#bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: #252526;
  border-bottom: 1px solid #3c3c3c;
}
#bar .title {
  font-weight: bold;
  font-size: 13px;
  flex: 1;
}
#bar button {
  background: #3a3a3a;
  color: #d4d4d4;
  border: 1px solid #3c3c3c;
  border-radius: 3px;
  padding: 5px 12px;
  font-size: 11px;
  cursor: pointer;
}
#bar button:active { background: #505050; }
#status {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #4ec9b0;
  flex-shrink: 0;
}
#status.offline { background: #f44747; }
#log {
  flex: 1;
  overflow-y: auto;
  padding: 6px 10px;
  -webkit-overflow-scrolling: touch;
}
.line {
  white-space: pre-wrap;
  word-break: break-all;
  padding: 1px 0;
  line-height: 1.6;
}
.line .ts { color: #858585; }
.line .lv { font-weight: bold; margin: 0 4px; }
.lv-DEBUG .lv { color: #569cd6; }
.lv-INFO .lv { color: #4ec9b0; }
.lv-WARNING .lv { color: #dcdcaa; }
.lv-ERROR { color: #f44747; }
.lv-CRITICAL { color: #569cd6; }
.lv-ERROR .lv { color: #f44747; }
.lv-CRITICAL .lv { color: #569cd6; }
</style>
</head>
<body>
<div id="bar">
  <span id="status"></span>
  <span class="title">taoSync 运行日志</span>
  <button id="btnClear">清空</button>
</div>
<div id="log"></div>
<script>
var lastSeq = 0;
var logEl = document.getElementById('log');
var statusEl = document.getElementById('status');

document.getElementById('btnClear').onclick = function() {
  logEl.innerHTML = '';
};

function nearBottom() {
  return logEl.scrollHeight - logEl.scrollTop - logEl.clientHeight < 80;
}

function escapeHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function poll() {
  fetch('/__log__?since=' + lastSeq)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      statusEl.classList.remove('offline');
      if (data.last_seq) lastSeq = data.last_seq;
      if (!data.entries || data.entries.length === 0) return;
      var scroll = nearBottom();
      data.entries.forEach(function(e) {
        var d = new Date(e.ts * 1000);
        var ts = d.getHours() + ':' +
                 String(d.getMinutes()).padStart(2,'0') + ':' +
                 String(d.getSeconds()).padStart(2,'0');
        var line = document.createElement('div');
        line.className = 'line lv-' + e.level;
        line.innerHTML = '<span class="ts">[' + ts + ']</span>' +
                         '<span class="lv">' + e.level + '</span>' +
                         escapeHtml(e.msg);
        logEl.appendChild(line);
      });
      while (logEl.children.length > 2000) {
        logEl.removeChild(logEl.firstChild);
      }
      if (scroll) logEl.scrollTop = logEl.scrollHeight;
    })
    .catch(function() { statusEl.classList.add('offline'); })
    .finally(function() { setTimeout(poll, 1500); });
}

// 标记日志页已激活，供 / 页面检测回退并跳回（防止右滑返回退到 taoSync）
sessionStorage.setItem('__logview_active__', '1');

// 阻止后退键回到首页/退出 Activity：p4a webview 先加载 / (首页) 作为
// 历史栈第 0 项，再由 loadUrl 跳到 /__logview__。这里用带 hash 的 URL
// （与无 hash 的当前页 URL 不同，确保 pushState 生成真实历史项，避免
// 某些 WebView 对同 URL pushState 的优化）压入多个缓冲项，形成较深
// 历史栈；后退触发 popstate 时立即补回缓冲项，使后退键只在日志页
// 内部循环，永远到不了首页。
(function() {
  var n = 0;
  function push() {
    n += 1;
    history.pushState({ i: n }, '', '#stay' + n);
  }
  push(); push(); push();
  window.addEventListener('popstate', function() { push(); });
  window.addEventListener('pageshow', function(e) { if (e.persisted) { push(); push(); } });
})();

poll();
</script>
</body>
</html>"""


class LogIndexHandler(RequestHandler):
    def get(self):
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.write(_LOG_PAGE_HTML)


class LogDataHandler(RequestHandler):
    def get(self):
        since = int(self.get_argument('since', 0))
        with _log_lock:
            entries = [e for e in _log_entries if e['seq'] > since]
            last_seq = _log_seq
        self.set_header('Content-Type', 'application/json')
        self.write({'entries': entries, 'last_seq': last_seq})


# ======================================================================
# 业务应用
# ======================================================================
FRONTEND_PATH = _app_dir


class MainIndex(RequestHandler):
    def get(self):
        # 默认根路径渲染 taoSync 前端服务页，
        # 保证直接访问 http://127.0.0.1:8023/ 打开的是 taoSync 页面。
        # Android WebView 由 main_android.py 的 loadUrl 单独加载 /__logview__。
        # 注入 JS：若是从日志页回退到此（右滑/后退手势），立即跳回日志页，
        # 防止退到 taoSync 页面；浏览器首次直接访问 / 不受影响（无标记）。
        with open(os.path.join(FRONTEND_PATH, "front", "index.html"),
                  'r', encoding='utf-8') as f:
            html = f.read()
        inject = (
            '<script>'
            'function __checkLogviewBack(){'
            'if(sessionStorage.getItem("__logview_active__")){'
            'sessionStorage.removeItem("__logview_active__");'
            'location.replace("/__logview__");'
            '}'
            '}'
            '__checkLogviewBack();'
            'window.addEventListener("pageshow",'
            'function(e){if(e.persisted)__checkLogviewBack();});'
            '</script>'
        )
        if '</head>' in html:
            html = html.replace('</head>', inject + '</head>', 1)
        else:
            html = inject + html
        self.set_header('Content-Type', 'text/html; charset=utf-8')
        self.write(html)


def make_business_app(server_cfg):
    return Application([
        (r"/__log__", LogDataHandler),
        (r"/__logview__", LogIndexHandler),
        (r"/svr/noAuth/login", systemController.Login),
        (r"/svr/user", systemController.User),
        (r"/svr/language", systemController.Language),
        (r"/svr/alist", jobController.Alist),
        (r"/svr/job", jobController.Job),
        (r"/svr/notify", notifyController.Notify),
        (r"/", MainIndex),
        (r"/(.*)", StaticFileHandler,
         {"path": os.path.join(FRONTEND_PATH, "front")})
    ], cookie_secret=server_cfg['passwdStr'])


async def main():
    _file_log('INFO', '服务进程正在初始化...')
    onStart.init()

    cfg = getConfig()
    server_cfg = cfg['server']
    port = int(server_cfg['port'])

    business_app = make_business_app(server_cfg)
    # 监听 0.0.0.0 允许外部设备访问；服务进程作为前台服务不会被冻结
    business_app.listen(port, address='0.0.0.0')
    _file_log('INFO', f'服务已启动: http://0.0.0.0:{port}/')

    logger = logging.getLogger()
    logger.critical(f'启动成功_/_Running at http://127.0.0.1:{port}/')

    await asyncio.Event().wait()


# p4a PythonService 直接执行此文件，不通过 __main__
try:
    asyncio.run(main())
except Exception as e:
    import traceback
    tb = traceback.format_exc()
    _append_log('ERROR', f'服务进程启动失败:\n{tb}')
    if _file_fp:
        try:
            _file_fp.write(tb)
            _file_fp.flush()
        except Exception:
            pass
    os._exit(1)
