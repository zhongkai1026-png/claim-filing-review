"""DeepSeek AI 审查连通性自检：验证 API Key 与审查调用是否正常。

运行：python test_ai.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

print("== AI 审查配置自检 ==\n")
from app import config  # noqa: E402
from app.services import llm  # noqa: E402

print(f"[1] 配置读取（系统内 AI 设置界面管理，数据库 ai_configs 表）")
cfg = llm.get_active_config()
print(f"    base_url : {cfg['base_url'] if cfg else '（无激活配置）'}")
print(f"    model    : {cfg['model'] if cfg else '（无激活配置）'}")
print(f"    name     : {cfg['name'] if cfg else '（无激活配置）'}")
print(f"    api_key  : {'已配置(' + cfg['api_key'][:6] + '****)' if cfg else '未配置'}")
if not cfg:
    print("    ❌ 未启用：请在系统右上角「⚙️ AI 设置」中添加并激活模型配置")
    print("       （或运行后端后访问 http://127.0.0.1:8000 → ⚙️ AI 设置）")
    sys.exit(1)

print(f"\n[2] API 连通性测试（调用 DeepSeek）")
reply = llm.chat([{"role": "user", "content": "请回复：连接成功"}],
                 temperature=0, max_tokens=50)
if reply:
    print(f"    ✅ 调用成功，返回：{reply.strip()[:60]}")
else:
    print("    ❌ 调用失败：请检查 API Key 是否有效、网络是否可达、余额是否充足")
    sys.exit(1)

print(f"\n[3] 审查方法论 Prompt 测试（模拟一次债权审查）")
from app.services import auditor  # noqa: E402
claim_json = '{"债权编号":"PC-001","债权人名称":"XX建材集团有限公司",' \
             '"申报本金":856000.00,"申报利息":12000.50,"申报其他":3000.00,' \
             '"申报总额":871000.50,"债权类型":"购销","债权种类":"购销",' \
             '"申报债权性质":"普通债权","涉诉涉执":"是"}'
material = "【材料：购销合同.pdf】\\nXX建材集团有限公司与债务人于2022年3月签订购销合同，" \
           "货款本金人民币 856000.00 元，约定逾期利息按年利率 8% 计算。" \
           "【材料：发票.pdf】\\n增值税发票若干，金额合计 856000.00 元。"
messages = [
    {"role": "system", "content": auditor.AUDIT_SYSTEM},
    {"role": "user", "content": auditor.AUDIT_USER
     .replace("{TYPE_STANDARD}", auditor._type_standard_text("购销"))
     .replace("{claim_json}", claim_json)
     .replace("{text_preview}", material)},
]
data = llm.chat_json(messages, temperature=0.1, max_tokens=config.AI_MAX_TOKENS)
if data:
    print(f"    ✅ 审查调用成功")
    print(f"    结论       : {data.get('conclusion')} / {data.get('review_result')}")
    print(f"    决策树级数 : {len(data.get('review_process') or [])}")
    print(f"    法律依据条数: {len(data.get('legal_basis') or [])}")
    print(f"    材料证据条数: {len(data.get('material_evidence') or [])}")
    print(f"    金额建议   : 本金 {data.get('suggested_principal')} "
          f"利息 {data.get('suggested_interest')} 其他 {data.get('suggested_others')}")
    print(f"    摘要       : {str(data.get('summary'))[:80]}")
    if len(data.get('review_process') or []) >= 7:
        print("\n    ✅ AI 审查完整（7 级决策树 + 材料证据 + 法律依据）")
    else:
        print("\n    ⚠️ 决策树不完整，请将输出发管理员检查")
else:
    print("    ❌ 审查调用失败（可能是上下文过长或 Key 权限问题）")

print("\n==================")
print("  自检完成")
print("==================")
