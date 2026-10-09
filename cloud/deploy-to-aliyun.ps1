# ============================================================
# 债权申报云端部署 · Windows 一键脚本（上传 + 部署 + 验证）
#
# 用法（在 PowerShell 中，进入 cloud 目录）:
#   .\deploy-to-aliyun.ps1 -Ip 8.130.44.159 [-Port 8080] [-KeyPath ""]
#
# 说明:
#   - root 密码只在你的终端提示处输入，脚本不保存、不上传、不进对话记录
#   - 若本机已有 SSH 公钥(~/.ssh/id_rsa.pub)，首次会尝试安装到服务器，之后免密
#   - 需要 Windows 自带 OpenSSH 客户端（Win10/11 一般已内置）
# ============================================================
param(
    [string]$Ip = "8.130.44.159",
    [int]$Port = 8080,
    [string]$KeyPath = ""   # 可选：SSH 私钥路径，如 C:\keys\aliyun.pem
)
$ErrorActionPreference = "Stop"

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$cloudDir = (Resolve-Path (Join-Path $here ".")).Path

# ---- 0. 检查 ssh / scp ----
foreach ($cmd in @("ssh", "scp")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Error "未找到 $cmd，请安装 OpenSSH 客户端（Windows 设置 → 应用 → 可选功能）"
        exit 1
    }
}
$keyArgs = @()
if ($KeyPath) { $keyArgs = @("-i", $KeyPath) }
$target = "root@${Ip}"

# ---- 0.5 可选：安装 SSH 公钥（仅本机已有公钥时，输入一次密码后后续免密）----
$pub = Join-Path $env:USERPROFILE ".ssh\id_rsa.pub"
if (-not $KeyPath -and (Test-Path $pub)) {
    Write-Host "检测到本机 SSH 公钥，尝试安装到服务器（只需输入一次密码）..." -ForegroundColor Cyan
    Get-Content $pub | ssh @keyArgs $target "mkdir -p ~/.ssh && chmod 700 ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys" 2>$null
}

# ---- 1. 上传 cloud/ 到 /root/ ----
Write-Host "==> [1/3] 上传 cloud/ 到服务器 /root/（如提示密码，请输入 root 密码）" -ForegroundColor Cyan
& scp @keyArgs -r "$cloudDir" "${target}:/root/"
if ($LASTEXITCODE -ne 0) { Write-Error "scp 上传失败（退出码 $LASTEXITCODE）"; exit 1 }

# ---- 2. 服务器内执行部署脚本 ----
Write-Host "==> [2/3] 执行部署脚本 deploy.sh $Port（如提示密码，请再次输入）" -ForegroundColor Cyan
& ssh @keyArgs $target "bash /root/cloud/deploy.sh $Port"
if ($LASTEXITCODE -ne 0) { Write-Error "部署失败（退出码 $LASTEXITCODE），请把上方输出贴回给我"; exit 1 }

# ---- 3. 验证 + 输出配置 ----
Write-Host "==> [3/3] 服务器内部验证 + 输出配置" -ForegroundColor Cyan
& ssh @keyArgs $target "echo '--- 健康检查 ---'; curl -s http://127.0.0.1:$Port/api/health; echo; echo '--- 配置信息 ---'; echo '申报链接: http://$Ip`:$Port/?project=项目码&case=案号&debtor=债务人'; echo -n '管理员令牌: '; grep CLOUD_ADMIN_TOKEN /opt/claim-receiver/.env | cut -d= -f2; echo -n '项目码: '; grep CLOUD_PROJECT_CODES /opt/claim-receiver/.env | cut -d= -f2"
if ($LASTEXITCODE -ne 0) { Write-Error "验证失败（退出码 $LASTEXITCODE）"; exit 1 }

Write-Host ""
Write-Host "==============================================================" -ForegroundColor Green
Write-Host " 部署完成！还剩最后一步（只能你操作）：" -ForegroundColor Green
Write-Host " 阿里云控制台 → ECS 实例 → 安全组 → 入方向 → 放行 TCP $Port（源 0.0.0.0/0）" -ForegroundColor Green
Write-Host " 然后浏览器打开上面的申报链接测试提交一份申报。" -ForegroundColor Green
Write-Host " 管理员令牌请复制保存（第二步本地拉取要用，勿外泄）。" -ForegroundColor Green
Write-Host "==============================================================" -ForegroundColor Green
