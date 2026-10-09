"""启动入口：自动选择可用端口（8000 被占用时自动切换 8001/8002…），
启动成功后自动打开浏览器。

用法：
    python run.py            # 自动选端口
    python run.py 8005       # 指定端口
"""
import socket
import sys
import webbrowser

import uvicorn


def find_free_port(start: int = 8000, tries: int = 20) -> int:
    """从 start 开始找第一个可绑定的端口。"""
    for port in range(start, start + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    return start


if __name__ == "__main__":
    if len(sys.argv) > 1:
        port = int(sys.argv[1])
    else:
        port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 50)
    print(f"  破产管理人债权申报与审查系统")
    print(f"  本机访问地址：{url}")
    print(f"  局域网访问：http://<本机IP>:{port}（需防火墙放行，见 share_lan.bat）")
    print("=" * 50)
    try:
        webbrowser.open(url)
    except Exception:
        pass
    # host=0.0.0.0：允许局域网内其他电脑访问（分享给同事/债权人）
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=False)
