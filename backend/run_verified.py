"""一键启动 + 自动验证：启动服务器、自检健康、打开浏览器、保持运行。

用法：python run_verified.py
"""
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def find_free_port(start: int = 8000, tries: int = 30) -> int:
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


def check_health(port: int):
    try:
        with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/api/health", timeout=3) as r:
            return r.status, r.read().decode("utf-8", "ignore")[:160]
    except Exception as e:
        return None, str(e)


def has_online_apply(port: int) -> bool:
    """探测运行中的服务是否含在线申报路由（GET 返回 405=路由存在；404=旧版）。"""
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/online-apply")
        with urllib.request.urlopen(req, timeout=3) as r:
            return True  # 理论上 GET 会 405，但能通说明路由在
    except urllib.error.HTTPError as e:
        return e.code == 405
    except Exception:
        return False


def main():
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 52)
    print("  破产管理人债权申报与审查系统 - 一键启动")
    print(f"  计划端口：{port}  |  地址：{url}")
    print("=" * 52)

    # 启动前检查：端口是否已有服务（可能是旧实例）
    st, body = check_health(port)
    if st == 200:
        if has_online_apply(port):
            print(f"  端口 {port} 已有我们的服务在运行（含在线申报模块）：{body}")
            print(f"  直接访问：{url}")
            try:
                webbrowser.open(url)
            except Exception:
                pass
            return
        print("=" * 52)
        print("  ❌ 端口上运行的是【旧版本】服务（不含在线申报模块）。")
        print("  请先关闭旧进程，再重新启动：")
        print("    1) 双击 stop.bat 停止旧服务")
        print("    2) 重新运行本脚本")
        print("=" * 52)
        return

    # 后台线程启动 uvicorn（host=0.0.0.0：允许局域网访问）
    import uvicorn

    def launch():
        uvicorn.run("app.main:app", host="0.0.0.0", port=port,
                    log_level="info")

    t = threading.Thread(target=launch, daemon=True)
    t.start()

    # 轮询健康检查（最多 30 秒）
    for i in range(60):
        time.sleep(0.5)
        st, body = check_health(port)
        if st == 200:
            print("-" * 52)
            print(f"  ✅ 服务器已启动成功！")
            print(f"  🌐 访问地址：{url}")
            print(f"  🩺 健康检查：{body}")
            print(f"  版本：2.0-methodology（新代码已生效）")
            print("-" * 52)
            try:
                webbrowser.open(url)
            except Exception:
                pass
            break
    else:
        print("-" * 52)
        print("  ❌ 30 秒内未检测到服务响应。")
        print("  请把本窗口的全部内容复制发给我排查。")
        print("-" * 52)

    # 保持主线程运行（服务器由后台线程提供）
    print("  服务器运行中，关闭本窗口即停止服务。")
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        print("\n  已停止")


if __name__ == "__main__":
    main()
