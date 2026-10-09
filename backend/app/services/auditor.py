"""债权审查服务：AI 审查（LLM，应用《破产债权审查操作指南》方法论）
+ 规则引擎降级 + 人工复核落库。"""
import json
import logging
from datetime import datetime

from .. import config
from ..database import SessionLocal
from ..models import AuditResult, Claim
from . import llm
from .parser import clean_text

logger = logging.getLogger(__name__)

# 提示词版本（写入 audit_results.prompt_version，便于历史结论追溯）
PROMPT_VERSION = "v2-2026-09"

# ---------------- 审查方法论（注入 Prompt） ----------------

DECISION_TREE = """【逐级审查决策树】（必须按顺序逐级审查，每一级给出结论并记录到 review_process）
第1级 主体资格：申报人是否为合同相对方/适格债权人？债权转让是否有效通知？不适格 → rejected
第2级 时效：是否超过诉讼时效（3年）或强制执行期间（2年）？超时效且无中断中止证据 → rejected
第3级 暂缓情形：涉诉涉裁待决/附条件未成就/涉刑未结/保证人将来求偿权 → partial
第4级 生效法律文书：已有生效判决/裁决/调解书 → 应当确认（既判力，虚假诉讼除外，司法解释三第7条）
第5级 债权性质：有财产担保/建设工程优先/职工/税款/普通/劣后（惩罚性债权）
第6级 金额核算：本金（合同+凭证+账册）；利息（法定上限，破产受理日止息）；
      违约金（补偿性=普通，超损失1.3倍部分=劣后）；外币（受理日汇率中间价）
第7级 特别要件：虚假债权嫌疑（申报与证据明显不符）→ rejected"""

FIVE_ELEMENTS = """【审查五要素】
1. 主体资格：申报人是否为合同相对方/适格债权人？债权转让是否有效通知？
2. 债权性质：有财产担保/建设工程优先/职工/税款/普通/劣后？是否主张优先受偿权？
3. 债权金额：本金是否正确？利息是否符合法定上限（民间借贷≤LPR四倍）？违约金是否为补偿性？
4. 时效性：是否超过诉讼时效（3年）？是否超过强制执行期间（2年）？
5. 特别要件：合同特殊条款？涉诉涉裁涉刑？生效法律文书？"""

# 核心通用规则（AI_PROMPT_PROFILE=basic 时使用，等价于 2026-09 之前的版本）
GENERAL_RULES_CORE = """【通用审查规则】
1. 特别法优于一般法（《企业破产法》优先于《民法典》）
2. 生效法律文书既判力，但虚假诉讼除外（《破产法司法解释三》第7条）
3. 认定不得超出申报范围（填写错误除外）
4. 举证责任在债权人：证据不足且未补正的，不予确认
5. 附利息债权自破产受理时停止计息（第46条第2款）
6. 保证人将来求偿权可申报，暂缓认定（第51条）
7. 管理人保持中立、独立、专业"""

# 扩展通用规则（默认使用）：在原 7 条基础上补齐程序与实体规则（来源：审查操作指南第二章）
GENERAL_RULES = """【通用审查规则】
1. 特别法优于一般法（《企业破产法》优先于《民法典》）
2. 生效法律文书既判力，但虚假诉讼除外（《破产法司法解释三》第7条）
3. 认定不得超出申报范围（填写错误除外，如"100000"误写为"10000"应允许更正）
4. 举证责任在债权人：证据不足且在申报期内未补正的，不予确认；审查须结合申报材料、债务人财务账册与业务情况综合认定
5. 附利息债权自破产受理时停止计息（第46条第2款）
6. 保证人将来求偿权可申报，暂缓认定；债权人最终申报全部债权时保证人债权不予认定（第51条）
7. 管理人保持中立、独立、专业，不应主动释明或提示债权人补充主张
8. 书面申报原则：非书面形式申报的，应要求补交书面文件
9. 原件核对：应与原件核对；财务账册有记载或业务经办人无异议的可不核对原件，真实性存疑的要求出示原件
10. 连带债权人认定为"一笔债权"（一人代表申报须有授权委托书），不得重复认定
11. 未到期债权在破产申请受理时视为到期
12. 附条件债权：条件已成就→确认；尚未成就→暂缓认定
13. 涉诉、涉裁、涉刑（同一法律关系）债权→暂缓认定；可协商撤回诉讼后直接确认，或等待生效法律文书
14. 债权转让须提交转让协议＋已通知债务人的证据；未通知→对债务人不发生效力，不予认定，要求以原债权人名义申报
15. 部分清偿的冲抵顺序（约定不明时）：实现债权的费用→利息→本金
16. 外币债权按法院受理破产申请之日人民币汇率中间价折算（无中间价则现汇买入价→现钞买入价）
17. 债权人未同时主张优先受偿权（建工价款/船舶航空器/财产担保）的，认定为普通债权（规则20）
18. 超过诉讼时效（规则21）、超过强制执行期间（规则22）的债权→不予确认，除非有中断/中止证据
19. 合同解除的损害赔偿按实际损失认定（第18条），包括直接损失与可得利益损失
20. 抵销权只能由债权人主张，管理人不主动通知抵销；劣后债权不得与债务人被动债权抵销"""

LEGAL_BASIS_LIST = """【法律依据清单】（审查时必须引用具体条文）
《企业破产法》第16/18/31-32/40/42/46/48/51/53/58/113条；
《破产法司法解释（三）》第7条；《民法典》第522/584-585/807条；
《民间借贷司法解释》第25条；《买卖合同司法解释》第18条第4款；
《民事诉讼法》关于诉讼时效、强制执行期间的规定"""

TYPE_STANDARDS = {
    "借贷": """【民间借贷类型化审查标准】（引用时标注「依据：借贷-N」）
1. 主体定性：自然人/法人之间资金融通；小额贷款公司**有金融业务许可证**的按金融债权、无证的按民间借贷处理
2. 合同效力：是否违反强制性规定；职业放贷人（一定期间内向不特定多人多次出借）可能构成非法经营致合同无效
3. 利率上限：不得超过合同成立时一年期 **LPR 的 4 倍**（《民间借贷司法解释》第25条），超出部分不予确认
4. 交付核验：款项是否实际交付、转账金额与借条是否一致；大额现金交付从严认定（资金来源、时间地点、在场人员）
5. 砍头息：预先扣除利息的，以**实际出借金额**为本金
6. 利滚利：前期利息计入后期本金的，不得超过以最初本金为基数的 LPR4 倍上限
7. 逾期利率＋违约金＋其他费用合计不得超过 LPR4 倍
8. 已还款冲抵顺序：实现债权的费用→利息→本金（约定不明的按此顺序）
9. 特殊情形：法定代表人个人借款用于企业→可认定企业债务；让与担保/以物抵债/阴阳合同/名为买卖实为借贷/入股款/刑民交叉（暂缓）
10. 保证责任：保证期间、连带责任范围、保证人将来求偿权（暂缓认定）
11. 受理日止息：《企业破产法》第46条，利息计算至受理日""",
    "购销": """【买卖合同（购销）类型化审查标准】（引用时标注「依据：购销-N」）
1. 主体资格：是否为合同适格当事人；真正利他合同第三人取得履行请求权→可推定有申报权；合同相对方与第三人均申报→协商确定一方
2. 履行状态：以**主要义务**是否履行完毕为标准（附随义务未履行不影响"已履行完毕"认定）
3. 已履行完毕：核验合同＋收货确认单＋发票＋已付款记录＋财务账册＋业务情况→确定本金
4. 违约金二分：补偿性违约金（以实际损失为限）＝普通债权；**超过实际损失 30%** 的部分＝惩罚性质→劣后债权
5. 逾期付款违约金按《买卖合同司法解释》第18条第4款确定
6. 质量保证金：原则上属普通债权（货币占有即所有）；已特定化（特户/封金/专用保证金）的可行使取回权
7. 未履行完毕：管理人可选择解除或继续履行（第18条）；继续履行且有利于债务人财产最大化的，已履行部分可认定为共益债务
8. 解除后损失按实际损失认定（直接损失＋可得利益损失）
9. 不动产买卖：消费者已付全部或大部分款项且未办理转移登记的，应予特别保护（购房者优先权）""",
    "金融": """【金融债权类型化审查标准】（引用时标注「依据：金融-N」）
1. 主合同与担保合同的有效性；担保登记情况与保证期间是否届满
2. 利息起止：自破产受理日停止计息（第46条）；不得因破产宣告触发加速到期而多计利息
3. 加速到期条款在破产程序中的效力审查
4. 罚息、复利按合同约定与监管规定审查，超出部分不予确认
5. 金融机构债权利率不受民间借贷 LPR4 倍限制（不适用民间借贷规则）
6. 债权转让/不良资产受让：转让协议有效性与通知义务（见"金融不良"标准）""",
    "金融不良": """【金融不良债权类型化审查标准】（引用时标注「依据：金融不良-N」）
1. 原始债权真实性：借款合同、放款凭证、对账单、借据链条是否完整
2. 债权转让协议有效性，转让链条是否连续（多次转让需逐手衔接）
3. 是否已通知债务人：未通知→对债务人不发生效力，要求以原债权人名义申报
4. 受让价格不影响债权数额认定（不得以低价受让为由核减）
5. 利息计算截止日：受理日止息；转让后利息归属按转让协议与公告确定
6. 受让人主体资格（金融资产管理公司/地方AMC/社会投资者）与政策限制""",
    "工程款": """【建设工程（工程款）类型化审查标准】（引用时标注「依据：工程款-N」）
1. 主体资格：施工合同相对方；转包、违法分包情形下**实际施工人**的认定
2. 优先受偿范围：工程价款（人工费、材料费、机械费、管理费、利润等），**不含利息、违约金、损害赔偿**
3. 行使期限：自发包人应当给付工程价款之日起 **18 个月**内行使，逾期丧失优先权
4. 顺位：建设工程价款优先受偿权 ＞ 抵押权 ＞ 普通债权（《民法典》第807条及建工司法解释）
5. 债权人未同时主张优先受偿权的→按普通债权认定（管理人不应主动释明）
6. 已付工程款、以房抵款、材料款垫付需核减；质量保证金按约定与履行证据审查
7. 工程量与结算依据：施工合同、结算书、签证单、审计报告、付款凭证""",
    "购房": """【购房者（不动产买卖）类型化审查标准】（引用时标注「依据：购房-N」）
1. 主体定性：是否为**消费者购房人**（生活居住需要），区别于经营者、投资客、以房抵债
2. 已付全部或大部分款项且未办理转移登记→特别保护（购房者优先权）
3. 已办理转移登记→不属于债务人财产，按取回权/别除权处理，不列入破产债权
4. 名为买卖实为借贷、以房抵债→按真实法律关系认定
5. 核验：网签备案、购房合同、付款凭证、发票、交房凭证
6. 程序：管理人主动查明与债权人申报两种路径，并履行公示程序""",
    "租赁": """【租赁合同类型化审查标准】（引用时标注「依据：租赁-N」）
1. 管理人有权决定解除或继续履行（第18条）；继续履行的租金作为共益债务
2. 解除后损失：区分**直接损失**与**可得利益损失**，一般仅确认直接损失
3. 装修残值：按合同约定或鉴定结论扣除折旧后认定
4. 预付租金、押金：按使用期间核减；押金性质按约定（返还请求权/取回权）
5. 欠付租金计算至合同解除或实际腾退之日，并与占有使用费区分（占有使用费属共益债务）""",
    "职工": """【职工债权类型化审查标准】（引用时标注「依据：职工-N」）
1. 职工身份：劳动合同、工资发放记录、社保缴纳记录；区分正式职工与劳务派遣、临时工、退休返聘
2. 法定范围（第113条）：工资、医疗费、伤残补助、抚恤费用，应划入个人账户的基本养老/基本医疗保险费用，法定经济补偿金
3. 高管工资：按企业**职工平均工资 3 倍**为限，超出部分按普通债权认定
4. 特殊类型：职工集资款按职工债权顺序审查；垫付职工工资款的垫付人主张追偿权的处理
5. 程序：制作职工债权清单并公示，接受职工异议；管理人不予更正的可诉""",
    "税收": """【税收债权类型化审查标准】（引用时标注「依据：税收-N」）
1. 税务机关的申报主体资格与申报范围
2. 税款范围：欠缴税款本金＋滞纳金；**滞纳金自破产受理日起不再计算**，且不属于第113条优先受偿范围（按普通债权处理）
3. 清偿顺位：在职工债权之后、普通债权之前
4. 破产申请受理后新产生的税款：属共益债务或破产费用（第42条）
5. 发票管理、税务注销等程序性事项""",
    "抵销": """【抵销权类型化审查标准】（引用时标注「依据：抵销-N」）
1. 行使主体：只能是债权人主张，管理人**不得主动**通知或主张抵销（除抵销使债务人财产受益外）
2. 积极要件：债权人与债务人互负债务、双方债务均已到期（或视为到期）、标的物种类品质相同
3. 消极要件（不得抵销）：受理后债务人的债务人取得他人对债务人的债权；债权人已知债务人不能清偿到期债务或破产申请事实而对债务人负担债务（除法律规定或破产申请 1 年前发生）；债务人的债务人已知该事实而取得债权
4. 债权人的担保债权与债务人的普通债权可相互抵销；**劣后债权不得抵销**
5. 债权人的主动债权须经申报与确认后方可主张抵销""",
    "取回权": """【破产取回权类型化审查标准】（引用时标注「依据：取回-N」）
1. 申请主体适格：财产所有权人、占有返还请求权人、担保物权人、用益物权人
2. 申请时限与方式是否合规
3. 一般取回权：标的物所有权归属 ＋ 该财产是否存在于破产财产中
4. 特别取回权：出卖人取回权、所有权保留、让与担保、融资租赁、代偿物取回权
5. 管理人应同时作法律判断（是否符合取回条件）与商业判断（继续履行是否更有利于债务人再生）
6. 已特定化的货币（特户/封金/专用保证金）可主张取回""",
}

# 类型匹配关键词（有序：先匹配更具体者），用于从 claim_type / claim_category / 材料文本推断类型
TYPE_MATCH = [
    ("金融不良", ("金融不良", "不良资产", "不良债权", "资产管理公司")),
    ("工程款", ("工程款", "工程债权", "工程价款", "建设工程", "施工合同", "实际施工人", "装饰装修")),
    ("购房", ("购房", "购房者", "商品房", "房屋买卖", "不动产买卖", "买房")),
    ("租赁", ("租赁", "租金", "出租", "承租", "融资租赁")),
    ("职工", ("职工", "工资", "劳动", "社保", "薪酬", "经济补偿金")),
    ("税收", ("税收", "税款", "税务", "滞纳金")),
    ("借贷", ("借贷", "民间借贷", "借款", "借条", "欠条", "出借")),
    ("购销", ("购销", "买卖合同", "货款", "供货", "送货", "对账")),
    ("金融", ("金融", "银行", "贷款", "票据", "融资")),
    ("抵销", ("抵销",)),
    ("取回权", ("取回权", "取回")),
]
# 仅凭材料文本兜底的类型：使用「特征短语」而非单词，降低假阳性
# （台账「债权类型」/「债权种类」都为空时才启用）
MATERIAL_MATCH = [
    ("金融不良", ("金融不良", "不良资产", "不良债权", "资产包", "债权转让协议")),
    ("工程款", ("建设工程施工合同", "工程价款优先受偿权", "实际施工人", "工程结算")),
    ("购房", ("商品房买卖合同", "购房者优先权", "购房款", "交房")),
    ("租赁", ("租赁合同", "房屋租赁", "融资租赁合同", "租金")),
    ("职工", ("劳动合同", "工资发放", "社保缴纳", "经济补偿金")),
    ("税收", ("税务机关", "欠缴税款", "滞纳金")),
    ("借贷", ("民间借贷", "借款合同", "借条", "出借人", "借款凭证")),
    ("购销", ("买卖合同", "购销合同", "供货合同", "送货单", "对账单")),
    ("金融", ("银行借款合同", "借款借据", "贷款合同", "承兑汇票", "保理合同")),
    ("抵销", ("抵销",)),
    ("取回权", ("取回权", "取回")),
]
# 精化关系：命中前者时不再重复注入后者（前者是后者的具体化）
TYPE_REFINE = {"金融不良": "金融"}
# 特征性极强、即使台账已给出类型也值得按材料精化/补充的类型
SPECIFIC_FROM_MATERIAL = ("金融不良", "抵销", "取回权")


def match_claim_types(claim_type: str = "", claim_category: str = "",
                      material_text: str = "") -> list[str]:
    """推断该债权命中的类型化标准（可多个，最多 2 个）。

    优先级：台账「债权类型」→「债权种类」→ 材料正文特征短语。
    - 台账两列都为空时：用材料特征短语兜底；
    - 台账已给出类型时：仅用材料补充/精化特征性极强的类型
      （金融不良、抵销、取回权），避免材料中的偶发表述覆盖台账口径。
    """
    matched: list[str] = []
    text = f"{claim_type or ''} {claim_category or ''}"
    for key, words in TYPE_MATCH:
        if any(w in text for w in words):
            matched.append(key)
        if len(matched) >= 2:
            break
    head = (material_text or "")[:4000]
    if head:
        source = MATERIAL_MATCH if not matched else [
            (k, p) for k, p in MATERIAL_MATCH if k in SPECIFIC_FROM_MATERIAL]
        for key, phrases in source:
            if key in matched or not any(p in head for p in phrases):
                continue
            parent = TYPE_REFINE.get(key)
            if parent and parent in matched:
                matched[matched.index(parent)] = key      # 由一般精化为具体
            elif len(matched) < 2:
                matched.append(key)
            if len(matched) >= 2:
                break
    # 精化去重：同时命中「金融不良」与「金融」时只保留前者
    for specific, generic in TYPE_REFINE.items():
        if specific in matched and generic in matched:
            matched.remove(generic)
    return matched


def _type_standard_text(claim_type: str, claim_category: str = "",
                        material_text: str = "") -> str:
    """按债权类型匹配注入类型化审查标准（兼容旧的单参数调用）。"""
    text, _ = build_type_standards(claim_type, claim_category, material_text)
    return text


def build_type_standards(claim_type: str, claim_category: str = "",
                         material_text: str = "") -> tuple[str, list[str]]:
    """返回（注入文本, 命中的类型列表）。"""
    matched = match_claim_types(claim_type, claim_category, material_text)
    if not matched:
        return ("【一般审查标准】按五要素与决策树逐级审查；如债权类型（民间借贷/买卖购销/金融/"
                "金融不良/建设工程/购房者/租赁/职工/税收/抵销/取回权）可识别，"
                "参照对应类型化标准执行。", [])
    parts = [TYPE_STANDARDS[k] for k in matched]
    if len(matched) > 1:
        parts.append("（本笔同时命中多个类型标准；若相互冲突，请在 risks 中说明适用取舍）")
    return "\n\n".join(parts), matched

def build_audit_system(rules: str = None) -> str:
    """组装 system 提示词（rules 可传核心规则以切换精简版）。"""
    return """你是资深的破产管理人债权审查专家，应用《企业破产债权审查操作指南》方法论，
依据《企业破产法》及相关司法解释，对债权人申报的债权进行专业审查。

{FIVE_ELEMENTS}

{DECISION_TREE}

{GENERAL_RULES}

{LEGAL_BASIS_LIST}

三类审查结论：
- confirmed（确认）：事实清楚+证据充分+法律关系明确+时效有效
- partial（暂缓认定）：涉诉涉裁待决/附条件未成就/涉刑未结/证据需补充/保证人将来求偿权
- rejected（不予确认）：主体不适格/超时效/证据不足未补正/虚假债权

撰写要求：
- 每一级的 detail 必须落到本案材料与事实，不得空泛复述规则；
- 若适用了下方【类型化审查标准】的具体条目，除在该级 detail 末尾标注「（依据：工程款-3）」外，
  还必须在 standard_refs 字段列出所引用的条目编号（如 ["工程款-3","工程款-4"]）；未适用则给空数组；
- **一切期间判断（诉讼时效 3 年、强制执行期间 2 年、建设工程价款优先权 18 个月、
  撤销权 6 个月/1 年、利息止息）必须以下方【案件信息】中的「破产受理日」为基准日**；
  破产受理日未填写时不得臆造、不得用其他日期替代，应在相应级别写明
  「项目未填写破产受理日，无法判断，需管理人补充后重新审查」，该级 result 记为「待核实」，
  并把该事项写入 risks；
- **日期一律照材料原文引用**：不得把材料中的年份改写成当前年份，也不得凭申报日/受理日反推材料未载明的日期；
- **【数据优先级规则】（重要）**：以台账字段作为申报数据、以材料文本作为核验依据，具体优先级为——
  ① 若台账 JSON 中「台账数据状态」为「已人工初审/编辑确认」，则该笔**台账数据优先**：金额、日期、性质、
     当事人等一律以台账为准，材料文本仅用于核验与补充说明；台账与材料不一致时，**按台账数据审查**，
     并在 risks 中用「台账记载 X，材料显示 Y」的形式列明差异，提示人工复核；
  ② 若「台账数据状态」为「系统解析预填（未经人工确认）」，则材料原文优先，并在 risks 中提示
     「台账字段系系统自动提取，需人工核对后确认」；
  ③ 无论哪种情形，材料正文始终用于核验申报是否成立、证据是否充分（真实性、材料齐备性审查不受上述优先级影响）；
- legal_basis 必须是可直接援引的具体条文，不得编造条号。

只输出 JSON，不要输出任何其他文字。""".format(
        FIVE_ELEMENTS=FIVE_ELEMENTS, DECISION_TREE=DECISION_TREE,
        GENERAL_RULES=rules or GENERAL_RULES, LEGAL_BASIS_LIST=LEGAL_BASIS_LIST)


AUDIT_SYSTEM = build_audit_system()

AUDIT_USER = """请审查以下债权申报信息，输出 JSON，必须包含这些键：
- conclusion: "认可" | "部分认可" | "不认可"（中文结论，用于台账展示）
- review_result: "confirmed" | "partial" | "rejected"（决策树最终结论）
- info_check: 材料与信息核查意见（字符串；必须逐份引用材料内容核验，说明材料是否齐全、信息是否一致）
- authenticity: 债权真实性审查意见（必须引用材料证据：合同/凭证/账单等是否支撑债权发生）
- legality: 债权合法性审查意见
- amount_review: 金额审查意见（必须把材料中显示的金额/利率/还款记录与申报金额逐项核对，给出核减建议）
- suggested_principal / suggested_interest / suggested_others: 建议审核金额（数字）
- nature_review: 债权性质与清偿顺序意见
- material_evidence: 从申报材料中提取的关键事实，字符串数组，
  如 ["《借款合同》显示借款本金500000元，约定年利率12%", "材料显示已还款100000元"]
- review_process: 决策树逐级审查过程，数组，每项为
  {"level": 1, "name": "主体资格", "result": "通过/暂缓/驳回", "detail": "该级审查说明"}
  必须覆盖全部7级，且 detail 尽量引用材料依据
- legal_basis: 引用的具体法律条文，字符串数组，如 ["《企业破产法》第46条第2款：附利息的债权自破产受理时起停止计息"]
- standard_refs: 本次实际引用的【类型化审查标准】条目编号，字符串数组，
  形如 ["工程款-3", "工程款-4"]；未引用类型化标准时给空数组 []
- risks: 风险提示（字符串数组）
- summary: 审查结论摘要（一句话）
{TYPE_STANDARD}

{CASE_INFO}

债权申报信息（JSON）：
{claim_json}

申报材料内容（按文件分段，审查时必须引用具体材料核验申报信息，
如材料中的合同金额/利率/还款记录/担保约定与申报是否一致）：
{text_preview}

如信息不足，在对应字段说明"材料信息不足，需人工核实"，不要臆测。"""


def build_case_info(project) -> str:
    """案件（项目）信息块：审查期间判断的基准数据，必须注入。

    尤其「破产受理日」——诉讼时效、执行期间、优先权 18 个月、撤销权期间与利息止息
    都以它为基准；缺失时须让模型明确说明"无法判断"而不是臆造日期。
    """
    if project is None:
        return "【案件信息】未能读取项目信息（案号/破产受理日均未知），如涉及期间判断请说明" \
               "「案件信息缺失，无法判断，需管理人补充」。"
    accept = (getattr(project, "accept_date", "") or "").strip()
    lines = [
        "【案件信息】（期间判断的基准，务必据此计算）",
        f"- 案号：{getattr(project, 'case_no', '') or '未填写'}",
        f"- 债务人：{getattr(project, 'debtor', '') or '未填写'}",
        f"- 管理人：{getattr(project, 'manager', '') or '未填写'}",
        f"- 破产受理日：{accept if accept else '未填写（关键基准缺失）'}",
    ]
    if not accept:
        lines.append("- 注意：破产受理日未填写，凡涉及诉讼时效、执行期间、优先权行使期限、"
                     "撤销权期间、利息止息的计算，一律写明「项目未填写破产受理日，无法判断，"
                     "需管理人补充后重新审查」，不得臆造日期或用申报日替代。")
    return "\n".join(lines)


def build_claim_dict(claim: Claim, text: str = "") -> dict:
    # 台账数据状态：经人工初审/编辑（或人工复核）确认过的，其数据优先于材料解析结果
    verified_at = getattr(claim, "verified_at", None)
    if verified_at:
        conf = f"已人工初审/编辑确认（{str(verified_at)[:16]}）"
    elif (claim.status or "") == "reviewed":
        conf = "已人工复核确认（未记录确认时间）"
    else:
        conf = "系统解析预填（未经人工确认）"
    return {
        "债权编号": claim.claim_no,
        "债权人名称": claim.name,
        "统一社会信用代码/身份证": claim.credit_code,
        "法定代表人": claim.legal_rep,
        "联系方式": claim.contact_info,
        "地址": claim.address,
        "代理人": claim.agent_name or "",
        "债权种类": claim.claim_category,
        "涉诉涉执": claim.litigation_status,
        "申报债权性质": claim.claim_nature,
        "申报时间": claim.claim_date,
        "申报本金": float(claim.principal or 0),
        "申报利息": float(claim.interest or 0),
        "申报其他": float(claim.others or 0),
        "申报总额": float(claim.claim_amount or 0),
        "担保情况": claim.guarantee_notes or "",
        "债权类型": claim.claim_type or "",
        "台账数据状态": conf,
    }


def _normalize_opinion(data: dict) -> dict:
    """规整 AI 输出：结论映射、金额、兼容缺失字段。"""
    conclusion = str(data.get("conclusion") or "部分认可")
    if conclusion not in ("认可", "部分认可", "不认可"):
        conclusion = "部分认可"
    review_result = str(data.get("review_result") or "").lower()
    if review_result not in ("confirmed", "partial", "rejected"):
        review_result = {"认可": "confirmed", "部分认可": "partial",
                         "不认可": "rejected"}.get(conclusion, "partial")
    for k in ("suggested_principal", "suggested_interest", "suggested_others"):
        try:
            data[k] = round(float(data.get(k) or 0), 2)
        except (TypeError, ValueError):
            data[k] = 0
    data["conclusion"] = conclusion
    data["review_result"] = review_result
    if not isinstance(data.get("risks"), list):
        data["risks"] = [str(data.get("risks") or "")]
    if not isinstance(data.get("legal_basis"), list):
        data["legal_basis"] = []
    if not isinstance(data.get("review_process"), list):
        data["review_process"] = []
    if not isinstance(data.get("material_evidence"), list):
        data["material_evidence"] = []
    if not isinstance(data.get("standard_refs"), list):
        data["standard_refs"] = []
    return data


def build_material_preview(claim: Claim, per_file: int = 4000,
                           max_total: int = 16000) -> str:
    """按文件分段构建材料文本（带文件名标识），供 LLM 逐份核验。

    - 每份文件文本截断到 per_file 字符
    - 总长超过 max_total 时停止并标注
    - 无文本的文件明确标注（可能是图片扫描件未识别）
    """
    parts = []
    total = 0
    truncated = False
    for f in claim.files:
        text = (f.ocr_text or "").strip()
        if not text:
            parts.append(f"【材料：{f.filename}】（无文本——可能是图片/扫描件未识别或内容为空）")
            continue
        t = clean_text(text, per_file)
        parts.append(f"【材料：{f.filename}】\n{t}")
        total += len(t)
        if total >= max_total:
            truncated = True
            break
    if truncated:
        parts.append("（其余材料文本过长已省略，请结合原始材料复核）")
    return "\n\n".join(parts)


def _material_evidence(text: str) -> list[str]:
    """从材料文本中提取关键证据事实（规则引擎用）。"""
    import re
    ev = []
    # 金额类：本金/金额/货款/借款/欠款 + 数值
    for m in re.finditer(
            r"(?:本金|金额|货款|借款|欠款|合计|共计)[^\n，。；]{0,8}?"
            r"([\d,]+(?:\.\d{1,2})?)\s*(万)?元", text):
        amt = float(m.group(1).replace(",", ""))
        if m.group(2):
            amt *= 10000
        ctx = text[max(0, m.start() - 12):m.end()].replace("\n", " ")
        if amt > 0 and len(ev) < 6:
            ev.append(f"材料显示金额：{ctx.strip()}（{amt:,.2f}元）")
    # 利率/利息约定
    for m in re.finditer(r"(?:年利率|利率|月利率)[^\n，。；]{0,10}?"
                         r"(\d+(?:\.\d+)?)\s*%", text):
        if len(ev) < 8:
            ev.append(f"材料显示利率约定：{m.group(0)}")
    # 还款/已还
    for kw in ("已还款", "已还", "还款记录", "偿还"):
        if kw in text and len(ev) < 8:
            i = text.find(kw)
            ev.append(f"材料出现「{kw}」：{text[max(0, i - 15):i + 25].strip()[:50]}")
    # 担保/抵押
    for kw in ("担保", "抵押", "质押", "保证人", "连带"):
        if kw in text and len(ev) < 8:
            i = text.find(kw)
            ev.append(f"材料出现「{kw}」：{text[max(0, i - 12):i + 22].strip()[:45]}")
    # 日期
    for m in re.finditer(r"20\d{2}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日", text):
        if len(ev) < 10:
            ev.append(f"材料出现日期：{m.group(0)}")
    # 去重
    seen, out = set(), []
    for e in ev:
        if e not in seen:
            seen.add(e)
            out.append(e)
    return out[:8]


def run_ai_audit(claim_id: int) -> None:
    """异步执行 AI 审查（在后台线程中调用）。"""
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if not claim:
            return
        result = db.query(AuditResult).filter(
            AuditResult.claim_id == claim_id).first()
        if not result:
            result = AuditResult(claim_id=claim_id)
            db.add(result)

        result.ai_status = "running"
        result.ai_error = ""
        db.commit()

        text_preview = build_material_preview(claim)
        claim_json = json.dumps(build_claim_dict(claim), ensure_ascii=False)
        # 案件信息（含破产受理日）：期间判断的基准，缺失时提示模型"无法判断"而非臆造
        from ..models import Project
        project = db.get(Project, claim.project_id)
        case_info = build_case_info(project)
        result.injected_case_info = case_info[:500]

        # 类型化标准：台账「债权类型」→「债权种类」→ 材料正文特征词
        profile = (config.AI_PROMPT_PROFILE or "full").lower()
        if profile == "basic":
            type_text, matched = _type_standard_text(""), []
            system_prompt = build_audit_system(GENERAL_RULES_CORE)
        else:
            type_text, matched = build_type_standards(
                claim.claim_type, claim.claim_category, text_preview)
            system_prompt = AUDIT_SYSTEM

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": AUDIT_USER
             .replace("{TYPE_STANDARD}", type_text)
             .replace("{CASE_INFO}", case_info)
             .replace("{claim_json}", claim_json)
             .replace("{text_preview}",
                      text_preview or "（无材料文本，仅有台账登记信息）")},
        ]
        # max_tokens 可配置（config.AI_MAX_TOKENS）：思考型模型的思考过程与正文共用额度，
        # 额度不足会导致正文为空或 JSON 截断（历史上写死 5000 曾引发该故障）
        data = llm.chat_json(messages, temperature=0.1,
                             max_tokens=config.AI_MAX_TOKENS)

        if not data:
            result.ai_status = "failed"
            reason = llm.get_last_error()
            result.ai_error = ("AI 审查失败：" + reason) if reason else \
                "AI 未返回有效结果，请检查模型配置或网络后重试"
            result.prompt_version = PROMPT_VERSION
            result.injected_standards = "、".join(matched)
            db.commit()
            return

        data = _normalize_opinion(data)
        result.ai_opinion = json.dumps(data, ensure_ascii=False)
        cfg = llm.get_active_config()
        result.ai_model = (cfg or {}).get("name", "") or config.AI_MODEL
        result.ai_status = "done"
        result.ai_error = ""          # 成功时清空历史错误
        result.prompt_version = PROMPT_VERSION
        result.injected_standards = "、".join(matched)
        db.commit()
    except Exception as e:  # noqa: BLE001
        logger.exception("AI 审查失败")
        try:
            result = db.query(AuditResult).filter(
                AuditResult.claim_id == claim_id).first()
            if result:
                result.ai_status = "failed"
                result.ai_error = str(e)[:500]
                db.commit()
        except Exception:
            db.rollback()
    finally:
        db.close()


def run_rule_audit(claim_id: int) -> dict:
    """规则引擎降级审查：未配置 AI 时按决策树框架生成初步意见。"""
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if not claim:
            return {"error": "债权不存在"}
        result = db.query(AuditResult).filter(
            AuditResult.claim_id == claim_id).first()
        if not result:
            result = AuditResult(claim_id=claim_id)
            db.add(result)

        amt = float(claim.claim_amount or 0)
        prin = float(claim.principal or 0)
        int_ = float(claim.interest or 0)
        oth = float(claim.others or 0)

        # 材料内容分析（规则引擎也基于上传材料审查）
        material_texts = [f.ocr_text for f in claim.files if f.ocr_text]
        material_text = "\n\n".join(material_texts)
        evidence = _material_evidence(material_text) if material_text.strip() else []
        material_note = (f"已解析 {len(material_texts)} 份材料文本，"
                         f"提取到 {len(evidence)} 条关键证据；"
                         if material_texts else "未解析到材料文本（可能是图片/扫描件未识别）；")

        issues = []
        review_process = []
        # 第1级 主体资格
        if not claim.name:
            issues.append("债权人名称未填写，主体资格待核实")
            review_process.append({"level": 1, "name": "主体资格",
                                   "result": "待核实", "detail": "债权人名称缺失，需人工确认申报主体是否适格"})
        else:
            review_process.append({"level": 1, "name": "主体资格", "result": "通过",
                                   "detail": f"申报主体为{claim.name}，需人工核对合同相对方/债权转让通知"})
        # 第2级 时效
        review_process.append({"level": 2, "name": "时效", "result": "待核实",
                               "detail": "需核对是否超过诉讼时效（3年）/强制执行期间（2年）"})
        # 第3级 暂缓情形
        if claim.litigation_status == "是":
            issues.append("涉诉涉执，需调取生效法律文书核实债权金额")
            review_process.append({"level": 3, "name": "暂缓情形", "result": "暂缓",
                                   "detail": "涉诉涉裁待决，建议暂缓认定（partial）"})
        else:
            review_process.append({"level": 3, "name": "暂缓情形", "result": "通过",
                                   "detail": "未见涉诉涉裁信息，继续审查"})
        # 第4级 生效法律文书
        review_process.append({"level": 4, "name": "生效法律文书", "result": "待核实",
                               "detail": "如有生效判决/裁决/调解书应确认（既判力，虚假诉讼除外）"})
        # 第5级 债权性质
        nature = claim.claim_nature or "待确认"
        if nature in ("工程款优先权", "抵押债权"):
            issues.append(f"主张{nature}，需核实优先权依据（合同、登记等）及清偿顺位")
        review_process.append({"level": 5, "name": "债权性质", "result": "待核实",
                               "detail": f"申报债权性质：{nature}；材料中担保/优先相关表述："
                                         f"{'有' if any('担保' in e or '抵押' in e or '优先' in e for e in evidence) else '未见'}"})
        # 第6级 金额核算（引用材料证据核对）
        amount_detail = (f"申报本金{prin:.2f}元/利息{int_:.2f}元/其他{oth:.2f}元，"
                         f"{material_note}"
                         + ("材料证据：" + "；".join(evidence[:4]) + "。" if evidence
                            else "材料中未提取到金额/利率等证据，需人工核对凭证并注意破产受理日止息。"))
        review_process.append({"level": 6, "name": "金额核算", "result": "待核实",
                               "detail": amount_detail})
        # 第7级 特别要件
        review_process.append({"level": 7, "name": "特别要件", "result": "待核实",
                               "detail": "需核对申报与证据是否一致，排除虚假债权嫌疑"})

        if not issues:
            issues.append("台账信息基本完整，建议结合申报材料逐项核对")
        if evidence:
            issues.append("材料证据有限，建议人工逐份核对原始材料后再定稿")

        data = {
            "conclusion": "部分认可",
            "review_result": "partial",
            "info_check": ("（规则引擎）材料与信息核查：%s申报主体为%s。"
                           % (material_note, claim.name or "（未填写）")),
            "authenticity": ("（规则引擎）真实性审查：%s"
                             % ("材料中提取到关键证据：" + "；".join(evidence)
                                if evidence else "暂无法自动核验，需人工对照申报材料原件。")),
            "legality": "（规则引擎）合法性审查：建议核对利息/违约金计算标准是否符合法律规定"
                        "（民间借贷≤LPR四倍，破产受理日止息）。",
            "amount_review": ("（规则引擎）金额审查：申报本金 %s 元、利息 %s 元、其他 %s 元；%s"
                              % (prin, int_, oth,
                                 "材料证据：" + "；".join(evidence)
                                 if evidence else "材料中未提取到金额/利率证据，建议人工逐项核减。")),
            "suggested_principal": prin,
            "suggested_interest": 0.0,
            "suggested_others": oth,
            "nature_review": "（规则引擎）债权性质：%s" % nature,
            "material_evidence": evidence,
            "review_process": review_process,
            "legal_basis": [
                "《企业破产法》第46条第2款：附利息的债权自破产受理时起停止计息",
                "《企业破产法》第58条：债权异议与确认程序",
            ],
            "risks": issues,
            "summary": "未配置 AI 审查接口，本次为规则引擎按决策树框架生成的初步意见，"
                       "请配置 DeepSeek API Key 后重新执行 AI 审查，并由人工复核定稿。",
        }
        result.ai_opinion = json.dumps(data, ensure_ascii=False)
        result.ai_model = "rule-engine"
        result.ai_status = "done"
        result.prompt_version = "rule-engine"
        result.injected_standards = ""
        db.commit()
        return data
    finally:
        db.close()


def save_manual_audit(claim_id: int, opinion: str, conclusion: str,
                      auditor: str, audited: dict | None) -> None:
    """保存人工复核意见与审核金额。"""
    db = SessionLocal()
    try:
        claim = db.get(Claim, claim_id)
        if not claim:
            return
        result = db.query(AuditResult).filter(
            AuditResult.claim_id == claim_id).first()
        if not result:
            result = AuditResult(claim_id=claim_id)
            db.add(result)

        result.manual_opinion = opinion
        result.audit_conclusion = conclusion
        result.auditor = auditor
        result.manual_status = "done"
        result.audited_at = datetime.now()

        if audited:
            for k in ("audited_principal", "audited_interest",
                      "audited_others", "audited_amount"):
                v = audited.get(k)
                if v is not None:
                    setattr(claim, k, round(float(v), 2))
            # 未显式给出总额时按分项求和
            if audited.get("audited_amount") is None:
                claim.audited_amount = round(
                    float(claim.audited_principal or 0)
                    + float(claim.audited_interest or 0)
                    + float(claim.audited_others or 0), 2)
        claim.status = "reviewed"
        # 人工复核同样视为人工确认：此后 AI 审查以台账数据为优先依据
        claim.verified_at = datetime.now()
        db.commit()
    finally:
        db.close()
