# 端到端流程测试（PowerShell 版）
$ErrorActionPreference = "Stop"
$BASE = "http://127.0.0.1:8000"
$passed = 0; $failed = 0

function Check([string]$name, [bool]$cond, [string]$extra = "") {
    if ($cond) { Write-Host "OK  $name" -ForegroundColor Green; $script:passed++ }
    else { Write-Host "FAIL $name  $extra" -ForegroundColor Red; $script:failed++ }
}

function PostJson([string]$url, $body) {
    $json = $body | ConvertTo-Json -Depth 6
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($json)
    Invoke-RestMethod -Method Post -Uri "$BASE$url" -ContentType "application/json; charset=utf-8" -Body $bytes -TimeoutSec 60
}

# 1. 创建项目
$p = PostJson "/api/projects" @{ name = "测试项目-XX公司破产清算"; case_no = "（2024）浙01破1号"; debtor = "XX制造有限公司"; manager = "XX律师事务所" }
Check "创建项目" ($null -ne $p.id) ($p | ConvertTo-Json -Compress)
$pid_ = $p.id

# 2. 生成测试申报材料
$txt = @"
XX建材集团有限公司债权申报书

申报人：XX建材集团有限公司
统一社会信用代码：91330100000012345A
法定代表人：张某某
联系电话：13800138000
联系地址：浙江省杭州市西湖区XX路88号
代理人：李某某，身份证号330106199001011234，电话13900139000

申报债权情况：
债务人与我司于2022年3月签订购销合同，截至申报日，
欠付货款本金人民币 856000.00 元，利息 12000.50 元，其他费用 3000.00 元。
申报债权性质：普通债权
涉诉情况：已起诉，杭州市西湖区人民法院审理中
"@
$tf = Join-Path $env:TEMP "test_claim.txt"
[System.IO.File]::WriteAllText($tf, $txt, [System.Text.Encoding]::UTF8)

# 3. 上传并解析（curl multipart，异步解析需轮询等待）
$upJson = curl.exe -s -X POST "$BASE/api/projects/$pid_/upload" -F "files=@$tf;type=text/plain;filename=claim.txt"
$c = $upJson | ConvertFrom-Json
Check "上传并解析生成债权" ($null -ne $c.id) $upJson
Check "债权编号 PC-001" ($c.claim_no -eq "PC-001") $c.claim_no
$cid = $c.id
$parsed = $false
for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 1
    $d = Invoke-RestMethod -Uri "$BASE/api/claims/$cid/detail" -TimeoutSec 30
    if ($d.files.Count -gt 0 -and ($d.files | Where-Object { $_.parse_status -eq "pending" }).Count -eq 0) { $parsed = $true; break }
}
Check "异步解析完成" $parsed "parse timeout"
$c = Invoke-RestMethod -Uri "$BASE/api/claims/$cid" -TimeoutSec 30
Check "债权人名称识别" ($c.name -eq "XX建材集团有限公司") $c.name
Check "信用代码识别" ($c.credit_code -eq "91330100000012345A") $c.credit_code
Check "法定代表人识别" ($c.legal_rep -eq "张某某") $c.legal_rep
Check "联系方式识别" ($c.contact_info -eq "13800138000") $c.contact_info
Check "涉诉状态识别" ($c.litigation_status -eq "是") $c.litigation_status
Check "申报性质识别" ($c.claim_nature -eq "普通债权") $c.claim_nature
Check "申报总额识别" ([math]::Abs([double]$c.claim_amount - 856000.00) -lt 0.01) $c.claim_amount

# 4. 详情与文件
$d = Invoke-RestMethod -Uri "$BASE/api/claims/$cid/detail" -TimeoutSec 30
Check "材料文件挂接" ($d.files.Count -eq 1) ("count=" + $d.files.Count)
Check "解析文本非空" ($d.files[0].ocr_text.Length -gt 50)
$preview = Invoke-WebRequest -Uri "$BASE/api/files/$($d.files[0].id)/preview" -UseBasicParsing -TimeoutSec 30
Check "材料预览可访问" ($preview.StatusCode -eq 200)

# 5. 台账查询与筛选
$lst = Invoke-RestMethod -Uri "$BASE/api/claims?project_id=$pid_" -TimeoutSec 30
Check "台账列表" ($lst.Count -eq 1)
$lst2 = Invoke-RestMethod -Uri "$BASE/api/claims?project_id=$pid_&keyword=建材" -TimeoutSec 30
Check "关键词筛选" ($lst2.Count -eq 1)

# 6. 编辑台账（总额自动求和）
$c2 = Invoke-RestMethod -Method Put -Uri "$BASE/api/claims/$cid" -ContentType "application/json" -Body '{"interest":12000.5,"others":3000.0}' -TimeoutSec 30
Check "总额自动求和" ([math]::Abs([double]$c2.claim_amount - 871000.50) -lt 0.01) $c2.claim_amount

# 7. 登记
$c3 = PostJson "/api/claims/$cid/register" @{}
Check "登记完成" ($c3.status -eq "registered") $c3.status

# 8. AI 审查（规则引擎降级，轮询）
$null = PostJson "/api/claims/$cid/ai-audit" @{}
$a = $null
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 500
    $a = Invoke-RestMethod -Uri "$BASE/api/claims/$cid/audit" -TimeoutSec 30
    if ($a.ai_status -eq "done" -or $a.ai_status -eq "failed") { break }
}
Check "AI审查完成" ($a.ai_status -eq "done") $a.ai_error
$opinion = $a.ai_opinion | ConvertFrom-Json
Check "审查结论字段" ($null -ne $opinion.conclusion) $opinion.conclusion
Check "建议金额字段" ($null -ne $opinion.suggested_principal)

# 9. 人工复核
$null = PostJson "/api/claims/$cid/manual-audit" @{
    audited_principal = 850000; audited_interest = 10000
    audit_conclusion = "部分认可"; manual_opinion = "核减本金6000元，因部分发票缺失"; auditor = "王管理人"
}
$c4 = Invoke-RestMethod -Uri "$BASE/api/claims/$cid" -TimeoutSec 30
Check "状态已复核" ($c4.status -eq "reviewed") $c4.status
Check "审核总额计算" ([math]::Abs([double]$c4.audited_amount - 860000.00) -lt 0.01) $c4.audited_amount

# 10. 导出
$excel = Invoke-WebRequest -Uri "$BASE/api/export/ledger?project_id=$pid_" -UseBasicParsing -TimeoutSec 60
Check "导出Excel台账" ($excel.StatusCode -eq 200 -and $excel.Content.Length -gt 1000) ("bytes=" + $excel.Content.Length)
$csv = Invoke-WebRequest -Uri "$BASE/api/export/ledger?project_id=$pid_&fmt=csv" -UseBasicParsing -TimeoutSec 30
$csvText = if ($csv.Content -is [byte[]]) { [System.Text.Encoding]::UTF8.GetString($csv.Content) } else { [string]$csv.Content }
Check "导出CSV台账" ($csvText.Contains("债权编号") -and $csvText.Contains("XX建材集团有限公司")) ($csvText.Substring(0, 60))
$opinionDoc = Invoke-WebRequest -Uri "$BASE/api/export/opinion/$cid" -UseBasicParsing -TimeoutSec 60
Check "导出意见书Word" ($opinionDoc.StatusCode -eq 200 -and $opinionDoc.Content.Length -gt 1000) ("bytes=" + $opinionDoc.Content.Length)
$zip = Invoke-WebRequest -Uri "$BASE/api/export/opinions?project_id=$pid_" -UseBasicParsing -TimeoutSec 60
Check "批量意见书zip" ($zip.StatusCode -eq 200 -and $zip.Content.Length -gt 1000) ("bytes=" + $zip.Content.Length)

# 11. 项目统计
$s = Invoke-RestMethod -Uri "$BASE/api/projects/$pid_/stats" -TimeoutSec 30
Check "项目统计" ($s.total -eq 1 -and $s.reviewed -eq 1 -and [math]::Abs([double]$s.sum_claimed - 871000.50) -lt 0.01) ($s | ConvertTo-Json -Compress)

Write-Host ""
Write-Host "结果：通过 $passed 项，失败 $failed 项" -ForegroundColor Cyan
if ($failed -gt 0) { exit 1 }
Write-Host "🎉 全流程测试通过" -ForegroundColor Green
