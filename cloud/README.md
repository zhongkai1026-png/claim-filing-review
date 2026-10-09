# 债权申报云端部署（第一步：阿里云接收暂存端）

数据流向：**申报页（阿里云）→ 接收服务暂存 → 本地工具拉取 → 写入本地 SQLite**

```
外部债权人浏览器
   │ 打开 http://8.130.44.159:8080/?project=项目码&case=案号
   ▼
阿里云 ECS (Ubuntu 22.04/24.04)
   ├─ /opt/claim-receiver/static/index.html   申报页（债权申报.html）
   └─ /opt/claim-receiver/ (FastAPI 接收服务, 端口 8080)
        ├─ data/cloud/{C-xxxx}/manifest.json  申报信息
        ├─ data/cloud/{C-xxxx}/files/         申报材料
        └─ 管理接口: 列表/打包/确认/删除（Bearer Token 鉴权）
   ▲
管理人本地工具（第二步）：HTTPS+Token 拉取 → online_claims → 导入台账 SQLite
```

## 一、你现在要做的 4 件事

1. **放行端口**：阿里云控制台 → ECS → 安全组 → 入方向放行 **TCP 8080**（备案后阶段再加 80/443）。
2. **上传本目录到服务器**（任选其一）：
   - 控制台「远程文件管理/Workbench」上传 `cloud/` 整个目录到 `/root/`；
   - 或本机执行 `scp -r cloud root@8.130.44.159:/root/`。
3. **执行部署**（登录服务器，SSH 或控制台 Workbench）：
   ```bash
   cd /root/cloud
   sudo bash deploy.sh 8080
   ```
   脚本自动装 Python 依赖、拷贝申报页、生成配置（管理员令牌/项目码）、注册并启动 systemd 服务，最后打印申报链接。
4. **验证**：
   ```bash
   curl http://127.0.0.1:8080/api/health          # 服务正常
   curl -I http://8.130.44.159:8080/              # 公网可访问申报页
   ```

## 二、配置（/opt/claim-receiver/.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `CLOUD_PORT` | 监听端口 | 8080 |
| `CLOUD_ADMIN_TOKEN` | 管理员令牌（本地工具拉取用，**勿外泄**） | 部署时随机生成 |
| `CLOUD_PROJECT_CODES` | 允许的项目码，逗号分隔（多案件各一个码） | DEMO2026 |

改完 `systemctl restart claim-receiver` 生效。

## 三、生成发给债权人的链接

```
http://8.130.44.159:8080/?project=DEMO2026&case=（2025）浙03破1号&debtor=某某公司&manager=某某律师事务所&deadline=2026-09-30
```

- `project` 必须是 `.env` 中 `CLOUD_PROJECT_CODES` 里的项目码，否则提交被拒；
- 页面会自动识别为「云端模式」：提交时 POST 到同源 `/api/apply`，成功返回云申报号 `C-xxxx`；
- 云端提交失败会自动降级为本地打包（下载 ZIP），不丢数据。

## 四、管理接口（本地工具第二步将调用）

| 接口 | 方法 | 说明 |
|---|---|---|
| `/api/apply` | POST | 债权人提交（multipart） |
| `/api/health` | GET | 健康检查 |
| `/api/admin/claims` | GET | 暂存列表（?status=pending） |
| `/api/admin/claims/{no}/package` | GET | 打包下载（manifest.json+材料 zip） |
| `/api/admin/claims/{no}/ack` | POST | 标记已导入 |
| `/api/admin/claims/{no}` | DELETE | 删除暂存 |

管理接口需请求头 `Authorization: Bearer <CLOUD_ADMIN_TOKEN>`。

## 五、常见问题

- **公网打不开**：安全组未放行 8080；或 ECS 是公网 NAT（检查实例是否绑定公网 IP）。
- **更新申报页后访问者仍看到旧版**：服务已对 HTML 响应加 `Cache-Control: no-cache, must-revalidate`（保留 ETag，未变更走 304），刷新即生效；但**浏览器此前已把旧页缓存**的，需要 `Ctrl+F5` 强刷一次（或在链接后加 `&v=2` 换缓存键）。今后更新页面只需覆盖 `/opt/claim-receiver/static/index.html`，无需重启服务。
- **上传被拒**：检查项目码是否在 `CLOUD_PROJECT_CODES`；单文件 >50MB；类型不在白名单。
- **提交 429**：单 IP 限流（默认 10 次/小时），稍后再试。
- **查看日志**：`journalctl -u claim-receiver -f`；重启：`systemctl restart claim-receiver`。

## 六、下一阶段（备案通过后）

1. 注册域名并完成 **ICP 备案**（阿里云控制台 → ICP 备案，周期约 1–2 周）；
2. 申请免费 SSL 证书，按 `nginx-https.conf.example` 配置 Nginx（静态页 + 反代 `/api` 到 127.0.0.1:8001）；
3. 把接收服务改到内网端口 `CLOUD_PORT=8001`，公网只暴露 443；
4. 本地工具增加 `cloud_sync` 拉取模块，自动写入台账 SQLite（见根目录 README 规划）。

## 安全说明

- 联调期用 HTTP + 非标准端口，仅建议内网/可信环境快速验证；对外正式使用必须 HTTPS；
- 暂存数据为敏感信息：建议定期 `DELETE /api/admin/claims/{no}` 清理已导入申报，或脚本定时清理 `data/cloud/`；
- 管理员令牌定期更换（改 `.env` 后重启服务）。
