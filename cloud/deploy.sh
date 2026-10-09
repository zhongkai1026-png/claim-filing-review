#!/usr/bin/env bash
# ============================================================
# 债权申报接收服务 · Ubuntu 一键部署脚本
# 用法: sudo bash deploy.sh [端口]   （默认端口 8080，联调期用非 80 端口免备案）
# 前提: 阿里云安全组已放行对应 TCP 端口
# ============================================================
set -euo pipefail

PORT="${1:-8080}"
APP_DIR="/opt/claim-receiver"
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SRC_DIR")"

echo "==> [1/5] 安装系统依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip openssl curl

echo "==> [2/5] 拷贝代码与申报页"
mkdir -p "$APP_DIR/static" "$APP_DIR/data"
cp -r "$SRC_DIR/receiver/." "$APP_DIR/"
if [ -f "$REPO_ROOT/债权申报.html" ]; then
  cp "$REPO_ROOT/债权申报.html" "$APP_DIR/static/index.html"
  echo "    已同步最新申报页（仓库根目录版本）"
elif [ -f "$SRC_DIR/receiver/static/index.html" ]; then
  cp "$SRC_DIR/receiver/static/index.html" "$APP_DIR/static/index.html"
  echo "    已同步申报页（cloud 包内版本）"
else
  echo "    ! 未找到申报页，请手动拷贝 债权申报.html 到 $APP_DIR/static/index.html"
fi
echo "==> [2.5/5] 拷贝申报模板（身份证明书 / 授权委托书）"
mkdir -p "$APP_DIR/static/templates"
for tpl in 法定代表人证明文件模板.docx 授权委托书模板.docx; do
  if [ -f "$REPO_ROOT/$tpl" ]; then
    cp "$REPO_ROOT/$tpl" "$APP_DIR/static/templates/" && echo "    已同步模板: $tpl"
  elif [ -f "$SRC_DIR/receiver/static/templates/$tpl" ]; then
    cp "$SRC_DIR/receiver/static/templates/$tpl" "$APP_DIR/static/templates/" && echo "    已同步模板: $tpl"
  fi
done

echo "==> [3/5] 创建虚拟环境并安装依赖"
if [ ! -d "$APP_DIR/venv" ]; then
  python3 -m venv "$APP_DIR/venv"
fi
"$APP_DIR/venv/bin/pip" install -q --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -r "$APP_DIR/requirements.txt"

echo "==> [4/5] 生成配置 .env（首次生成，之后请直接编辑该文件）"
if [ ! -f "$APP_DIR/.env" ]; then
  TOKEN="${CLOUD_ADMIN_TOKEN:-$(openssl rand -hex 16)}"
  CODES="${CLOUD_PROJECT_CODES:-DEMO2026}"
  cat > "$APP_DIR/.env" <<EOF
CLOUD_PORT=$PORT
CLOUD_ADMIN_TOKEN=$TOKEN
CLOUD_PROJECT_CODES=$CODES
EOF
  echo "    管理员令牌: $TOKEN"
  echo "    项目码(可多个用逗号分隔): $CODES"
else
  echo "    .env 已存在，跳过生成（编辑 $APP_DIR/.env 后 systemctl restart claim-receiver 生效）"
fi

echo "==> [5/5] 注册 systemd 服务并启动"
sed "s|__APP_DIR__|$APP_DIR|g" "$SRC_DIR/claim-receiver.service" > /etc/systemd/system/claim-receiver.service
systemctl daemon-reload
systemctl enable claim-receiver >/dev/null 2>&1
systemctl restart claim-receiver
sleep 2

if ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow "$PORT/tcp" >/dev/null 2>&1 || true
fi

TOKEN_VAL="$(grep CLOUD_ADMIN_TOKEN "$APP_DIR/.env" | cut -d= -f2)"
CODES_VAL="$(grep CLOUD_PROJECT_CODES "$APP_DIR/.env" | cut -d= -f2)"
IP="$(curl -s --max-time 3 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"

echo ""
echo "=============================================================="
echo " 部署完成 ✅"
echo ""
echo " 健康检查:   curl http://127.0.0.1:$PORT/api/health"
echo " 申报链接:   http://$IP:$PORT/?project=项目码&case=案号&debtor=债务人"
echo " 管理员令牌: $TOKEN_VAL   （本地工具拉取时配置，勿外泄）"
echo " 项目码:     $CODES_VAL   （可编辑 .env 增加，如 ABC001,ABC002）"
echo ""
echo " 请确认阿里云安全组已放行 TCP $PORT"
echo "=============================================================="
