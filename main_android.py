"""
taoSync Android 主进程入口（PythonActivity）。

职责：
1. 启动前台服务（service/main.py 运行 Tornado 8023，在 :pythonservice 进程）
2. 等待 8023 就绪
3. WebView 加载日志页面 http://localhost:8023/__logview__

业务逻辑在服务进程运行，即使主进程被 ColorOS 冻结，8023 仍可访问。
主进程日志仅写文件，用于诊断启动问题。
"""
import os
import sys
import time
import socket
import threading
import warnings

warnings.filterwarnings('ignore', message='.*character detection dependency.*')

# ======================================================================
# 主进程文件日志（仅诊断用，不显示在页面）
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


def _log(level, msg):
    msg = msg.rstrip('\n')
    if not msg:
        return
    if _file_fp:
        try:
            _file_fp.write(f'[主进程][{level}] {msg}\n')
            _file_fp.flush()
        except Exception:
            pass


_log('INFO', '=== taoSync 主进程启动 ===')
_log('INFO', f'Python: {sys.version}')
_log('INFO', f'cwd: {os.getcwd()}')


def _safe_exit(code=0):
    _log('CRITICAL', f'主进程退出 (code={code})')
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
    _log('ERROR', f'未捕获异常:\n{tb}')


sys.excepthook = _excepthook


# ======================================================================
# 等待端口就绪
# ======================================================================
def _wait_port(host, port, timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except (OSError, socket.error):
            time.sleep(0.5)
    return False


# ======================================================================
# 主流程
# ======================================================================
def _run():
    PORT = 8023

    try:
        from jnius import autoclass, cast
        _log('INFO', 'pyjnius 导入成功')
    except ImportError as e:
        _log('ERROR', f'pyjnius 导入失败: {e}')
        _safe_exit(1)
        return

    try:
        PythonActivity = autoclass('org.kivy.android.PythonActivity')
        Context = autoclass('android.content.Context')
        Build_VERSION = autoclass('android.os.Build$VERSION')

        activity = PythonActivity.mActivity
        if activity is None:
            _log('ERROR', 'PythonActivity.mActivity 为 None')
            _safe_exit(1)
            return
        sdk_int = Build_VERSION.SDK_INT
        _log('INFO', f'获取 Activity 成功，SDK_INT={sdk_int}')

        # 1. 启动后台服务（业务 Tornado 在服务进程中运行，不显示通知栏通知）
        # 注意：PythonActivity.start_service 内部 showForegroundNotification=true，
        # 即使标题/描述为空仍会显示前台服务通知；必须用 start_service_not_as_foreground
        # （showForegroundNotification=false）才能彻底不显示通知栏通知。
        try:
            PythonActivity.start_service_not_as_foreground('', '', '')
            _log('INFO', '后台服务已启动，等待 8023 就绪...')
        except Exception as e:
            _log('ERROR', f'启动后台服务失败: {e}')
            _safe_exit(1)
            return

        # 2. 等待服务进程的 Tornado 就绪
        if _wait_port('127.0.0.1', PORT, timeout=30):
            _log('INFO', f'8023 已就绪')
        else:
            _log('ERROR', f'8023 在 30 秒内未就绪')
            _safe_exit(1)
            return

        # 3. 请求电池优化白名单（辅助保活）
        try:
            Settings = autoclass('android.provider.Settings')
            Uri = autoclass('android.net.Uri')
            Intent = autoclass('android.content.Intent')
            pm = cast('android.os.PowerManager',
                      activity.getSystemService(Context.POWER_SERVICE))
            pkg = activity.getPackageName()
            if not pm.isIgnoringBatteryOptimizations(pkg):
                _log('INFO', '请求电池优化白名单')
                intent = Intent()
                intent.setAction(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
                intent.setData(Uri.parse('package:' + pkg))
                activity.startActivity(intent)
            else:
                _log('INFO', '已在电池优化白名单中')
        except Exception as e:
            _log('ERROR', f'请求电池优化白名单失败: {e}')

        # 4. WebView 加载日志页面
        try:
            PythonActivity.loadUrl(f'http://localhost:{PORT}/__logview__')
            _log('INFO', f'WebView 已加载 http://localhost:{PORT}/__logview__')
        except Exception as e:
            _log('ERROR', f'WebView 跳转失败: {e}')

        # 5. 清空 WebView 历史栈，彻底阻止右滑/后退返回到 taoSync 首页
        # p4a webview bootstrap 历史栈为 [_load.html(0), /(1), /__logview__(2)]，
        # onKeyDown 在 currentIndex>1 时会 goBack 到 /（taoSync 首页）。
        # WebViewLoader 在端口就绪后 loadUrl("http://127.0.0.1:port/")（根路径硬编码），
        # 之后本脚本的 loadUrl(/__logview__) 才进栈。这里 loadUrl 后延迟调用
        # WebView.clearHistory() 清空历史，使后退键无路可退（走双击退出逻辑）。
        # mWebView 是 PythonActivity 的 protected static 字段，pyjnius 可反射访问。
        try:
            WebView = autoclass('android.webkit.WebView')
            wv = activity.mWebView
            if wv is not None:
                def _clear_history():
                    # clearHistory 必须在当前页（/__logview__）加载完成后调用才有效；
                    # 否则会清掉刚加载的日志页。等待页面渲染。
                    time.sleep(1.5)
                    try:
                        wv.clearHistory()
                        _log('INFO', 'WebView 历史栈已清空')
                    except Exception as e:
                        _log('ERROR', f'clearHistory 失败: {e}')
                threading.Thread(target=_clear_history, daemon=True).start()
            else:
                _log('ERROR', 'mWebView 为 None，无法清空历史栈')
        except Exception as e:
            _log('ERROR', f'获取 mWebView 失败: {e}')

    except Exception as e:
        import traceback
        _log('ERROR', f'主流程异常: {traceback.format_exc()}')
        _safe_exit(1)


_run()

# 主进程保持存活（不退出，否则 Activity 可能被销毁）
_log('INFO', '主进程进入等待')
threading.Event().wait()
