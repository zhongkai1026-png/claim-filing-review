"""在线申报模块诊断：检查 8000-8020 端口哪个在运行、是否为最新代码。"""
import socket
import subprocess
import sys
import urllib.error
import urllib.request

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def port_open(port):
    with socket.socket() as s:
        s.settimeout(0.3)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False


def http_code(url):
    try:
        with urllib.request.urlopen(url, timeout=2) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def find_pid(port):
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "tcp"],
                             capture_output=True, timeout=5).stdout
        out = out.decode("gbk", errors="replace")
        for line in out.splitlines():
            if f"127.0.0.1:{port}" in line and "LISTENING" in line:
                return line.split()[-1]
    except Exception:
        pass
    return None


def cmdline(pid):
    try:
        ps = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             f"(Get-CimInstance Win32_Process -Filter 'ProcessId={pid}').CommandLine"],
            capture_output=True, timeout=10)
        return ps.stdout.decode("gbk", errors="replace").strip()
    except Exception:
        return "?"


print("=" * 62)
print("  在线申报模块诊断（自动扫描 8000-8020 端口）")
print("=" * 62)
found = False
for port in range(8000, 8021):
    if not port_open(port):
        continue
    found = True
    h = http_code(f"http://127.0.0.1:{port}/api/health")
    oc = http_code(f"http://127.0.0.1:{port}/api/online-apply")
    # oc: 405=路由存在(新版本正常)  404=旧版本(没有该接口)  None=不通
    tag = "✅ 新版本（含在线申报）" if oc == 405 else "❌ 旧版本（无在线申报接口）"
    pid = find_pid(port)
    cl = cmdline(pid) if pid else "?"
    print(f"\n端口 {port}   health={h}   online-apply探测={oc}")
    print(f"  状态：{tag}")
    print(f"  PID={pid}   进程命令行：{cl[:220]}")
if not found:
    print("\n❌ 8000-8020 端口没有任何服务在运行！")
    print("   请先启动：cd backend && python run_verified.py")
print("\n" + "=" * 62)
print("  判定方法：")
print("   - 全部端口显示【旧版本】→ 旧进程没杀掉，执行 stop.bat 后再启动")
print("   - 显示【新版本】但你浏览器仍 405 → 浏览器还开着旧端口页面，换新端口访问")
print("   - 没有任何服务 → 后端根本没在运行")
print("=" * 62)
