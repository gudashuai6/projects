#!/usr/bin/env python3
"""Build the D2RS project showcase website from GitHub issues."""
import json, re, csv, subprocess, html as E
from datetime import datetime, timezone, timedelta

CST = timezone(timedelta(hours=8))
UPDATE_TIME = datetime.now(CST).strftime('%Y-%m-%d %H:%M CST')

# ══════════════════════════════════════════════════════════════════════════════
# 1. Load data
# ══════════════════════════════════════════════════════════════════════════════
students = {}
with open('/Users/gaoch/GitHub/D2RS-2026spring/members/data/students/student-list.csv',
          encoding='utf-8-sig') as f:
    for row in csv.DictReader(f):
        students[row['学号']] = row['姓名']

with open('/tmp/student_github_map.json') as f:
    id_to_github = json.load(f)
github_to_id = {v: k for k, v in id_to_github.items()}

result = subprocess.run(
    ['gh', 'issue', 'list', '--repo', 'D2RS-2026spring/projects',
     '--state', 'all', '--limit', '200', '--json', 'number,body,title,author'],
    capture_output=True, text=True,
    cwd='/Users/gaoch/GitHub/D2RS-2026spring/projects')
issues = json.loads(result.stdout)

# ══════════════════════════════════════════════════════════════════════════════
# 2. Parse issues → extract members (with leader), repo, DOI
# ══════════════════════════════════════════════════════════════════════════════
parsed = []
for issue in issues:
    body = issue.get('body', '') or ''
    num = issue['number']
    title = issue.get('title', '').strip()
    author_login = issue['author']['login']

    # Resolve leader student ID
    leader_sid = github_to_id.get(author_login)
    # Fallback 1: author not in mapping — try @mention in body
    if not leader_sid:
        for m in re.findall(r'@([a-zA-Z0-9][\w.-]*)', body):
            if m.lower() == author_login.lower() and m in github_to_id:
                leader_sid = github_to_id[m]
                break
    # Fallback 2: find author's student ID from the line containing their login
    if not leader_sid:
        for line in body.split('\n'):
            if author_login in line:
                for sid in re.findall(r'\d{13}', line):
                    if sid in students:
                        leader_sid = sid
                        break
            if leader_sid:
                break

    # Collect all member student IDs
    ids = {sid for sid in re.findall(r'\d{13}', body) if sid in students}
    for m in re.findall(r'@([a-zA-Z0-9][\w.-]*)', body):
        if m in github_to_id:
            ids.add(github_to_id[m])
    if leader_sid:
        ids.add(leader_sid)

    # Build member list: leader first, then others sorted by name
    members = []
    if leader_sid and leader_sid in students:
        members.append({'sid': leader_sid, 'name': students[leader_sid],
                        'gh': author_login, 'leader': True})
    # Fallback 3: author unidentified — default first listed member as leader
    if not leader_sid and ids:
        first_sid = sorted(ids)[0]
        if first_sid in students:
            leader_sid = first_sid
            members.append({'sid': first_sid, 'name': students[first_sid],
                            'gh': id_to_github.get(first_sid), 'leader': True})
    for sid in sorted(ids):
        if sid == leader_sid:
            continue
        if sid in students:
            gh = id_to_github.get(sid)
            members.append({'sid': sid, 'name': students[sid],
                            'gh': gh, 'leader': False})

    # Repo URL — skip image/file attachments
    repos = [r for r in re.findall(r'github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)', body)
             if not r.startswith('user-attachments')]
    repo = repos[0].removesuffix('.git') if repos else None

    # DOI — allowlist approach: only [a-zA-Z0-9/\-_.:] are valid DOI chars
    raw = re.findall(r'10\.\d{4,}/[a-zA-Z0-9/\-_.:]+', body)
    from_org = re.findall(r'doi\.org/(10\.\d{4,}/[a-zA-Z0-9/\-_.:]+)', body)
    candidates = from_org + [d for d in raw if d not in from_org]
    DOI_FIX = {65: '10.48550/arXiv.2412.10448'}
    doi = DOI_FIX.get(num)
    if not doi:
        for c in candidates:
            if re.match(r'^10\.\d{4,}/', c):
                doi = c
                break

    # Journal / paper hint from body
    journal = ''
    jmatch = re.search(
        r'(?:发表于|published in|Journal[:\s]+|期刊[:\s]*|iMeta|Nature|Science|PNAS|'
        r'Geoderma|CATENA|GCB|SOIL|mSphere|Sustainability|JOSS|IEEE|'
        r'Comput Struct Biotechnol J|Applied Soil Ecology|'
        r'Global Change Biology|Nature Communications|Nature Food|'
        r'Nature Geoscience|ACS EST|J Environmental Management|'
        r'International Journal of Hydrogen Energy|Environ Sci Technol|'
        r'Remote Sensing|ISPRS|Water Resources Research|'
        r'Ecological Monographs|New Phytologist|Ecology|'
        r'Microbiome|iMeta)',
        body, re.I)
    if jmatch:
        journal = jmatch.group(0)

    parsed.append(dict(num=num, title=title, author=author_login,
                       members=members, repo=repo, doi=doi, journal=journal,
                       body=body))

# ══════════════════════════════════════════════════════════════════════════════
# 3. Deduplicate by member-set
# ══════════════════════════════════════════════════════════════════════════════
seen = {}
for p in parsed:
    key = tuple(m['sid'] for m in p['members']) or f"__{p['author']}_{p['num']}"
    if key not in seen:
        seen[key] = p
    else:
        old = seen[key]
        if len(p['body']) > len(old['body']):
            seen[key] = p

unique = sorted(seen.values(), key=lambda x: -x['num'])

# ══════════════════════════════════════════════════════════════════════════════
# 3b. Check repo transfer status
# ══════════════════════════════════════════════════════════════════════════════
org_result = subprocess.run(
    ['gh', 'repo', 'list', 'D2RS-2026spring', '--limit', '200', '--json', 'name'],
    capture_output=True, text=True)
org_repo_names = {r['name'].lower() for r in json.loads(org_result.stdout)}

def check_transfer(p):
    """Check if repo is in D2RS-2026spring org. Returns (transferred, is_student_repo, has_repo)."""
    repo = p.get('repo')
    if not repo:
        return False, False, False  # no repo link at all
    owner, name = repo.split('/', 1)
    if owner.lower() == 'd2rs-2026spring':
        return True, True, True
    if name.lower() in org_repo_names:
        return True, True, True
    # Check via API (handles redirects from transfers)
    try:
        r = subprocess.run(
            ['gh', 'api', f'repos/{owner}/{name}', '--jq', '.owner.login'],
            capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip().lower() == 'd2rs-2026spring':
            return True, True, True
    except Exception:
        pass
    # Is the owner one of our students?
    is_student = owner in github_to_id  # github_to_id maps username → student ID
    return False, is_student, True

for p in unique:
    transferred, is_student, has_repo = check_transfer(p)
    p['transferred'] = transferred
    p['is_student_repo'] = is_student
    p['has_repo'] = has_repo
    if not has_repo:
        print(f"   NO repo: #{p['num']} {p['title'][:40]}")
    elif not transferred and is_student:
        print(f"   NOT transferred (student): #{p['num']} repo={p.get('repo','')}")
need_transfer = [p for p in unique if not p['transferred'] and p['is_student_repo']]
no_repo = [p for p in unique if not p['has_repo']]
submitted = [p for p in unique if p['transferred']]
submitted_count = len(submitted)
print(f"   submitted: {submitted_count}, need transfer: {len(need_transfer)}, no repo: {len(no_repo)}")

# ══════════════════════════════════════════════════════════════════════════════
# 4. Hand-curated clean descriptions (keyed by issue number)
# ══════════════════════════════════════════════════════════════════════════════
DESC = {
    107: "复现 node2vec 二阶带偏随机游走框架，在合成菌群互作网络上验证特征提取能力，解决 NumPy 2.0+ 兼容性问题。",
    106: "基于壳斗科 12 个种群 1185 粒种子的萌发实验，复现种子质量分布直方图与 PCA 主成分分析。",
    105: "使用 R Markdown 复现柑橘养分利用课题组官网四个模块，体验文学化编程在网页呈现中的应用。",
    104: "同 #105，另一小组成员提交版本。",
    103: "基于 CSDLv2 公开数据集，使用 R 复现中国表层土壤 SOC、TN 和 C/N 比的空间分布图。",
    102: "复现合成芽孢杆菌菌群 (SynCom) 组装分析，探索细菌社会互作如何协同促进黄瓜生长。",
    101: "复现论文 Figure 4 的微生物富集分析，使用 R 完成 16S rRNA 物种组成柱状图与气泡图。",
    100: "复现生物分子-黏土界面吸附机制，包含吸附等温线、XRD 图谱与 MD 扩散轨迹的 Python 分析。",
    99: "复现土壤有机碳分子组成的大陆尺度空间分布与权衡关系，使用 R 完成统计分析与可视化。",
    98: "复现三峡库区不同植被恢复方式下土壤物理指标柱状图、功能雷达图与综合质量指数 (SPQI)。",
    97: "搭建 R+renv 环境，研究 4 个施氮水平对水稻株高、SPAD 叶绿素和产量的影响。",
    96: "同 #98，另一小组成员提交的复现版本。",
    95: "复现灌溉农业全球能源使用与碳排放的统计分析，包含随机森林建模与 ROC 曲线。",
    94: "基于农业废弃物资源化利用文献的可重复数据分析。",
    93: "使用 R+Python 完成大豆在 4 个施硫处理下的方差分析、多重比较和可视化。",
    92: "使用 renv 管理 R 环境，复现藻类胞外聚合物提取实验的数据处理与可视化流程。",
    91: "对比青藏高原与阿拉斯加多年冻土 SOC 累积机制，复现酶活性区域对比图。",
    90: "复现 RNA-seq 全流程标准化方案，涵盖实验设计、质控、比对定量到差异分析。",
    89: "同 #90，小组另一成员提交版本。",
    88: "同 #90，小组另一成员提交版本。",
    87: "同 #90，小组另一成员提交版本。",
    86: "同 #90，小组另一成员提交版本。",
    85: "同 #90，小组另一成员提交版本。",
    84: "复现百年尺度土地利用变化对德国有机碳储量影响的全流程分析与图表。",
    83: "复现钼和氮肥对烟草氮代谢与氨基酸含量影响的柱状图分析。",
    82: "对 PNAS 2018 论文进行可重复性评估，发现其代码缺乏文档、数据未完全公开。",
    81: "在 Colab 上复现 MangoMamba 轻量级芒果叶病害检测模型，验证 98.86% 准确率。",
    80: "基于 OpenCV LBPH 算法实现轻量级人脸识别，解决 Python 3.13 与 dlib 的兼容问题。",
    79: "同 #80，小组另一成员提交版本。",
    78: "对氮代谢转录调控网络论文 5 幅关键图进行可重复性评估与部分复现。",
    77: "复现全球白蚁对凋落物分解影响的荟萃分析图 (lnRR 响应比与气候驱动因子)。",
    76: "基于 R 语言开源遥感工具包 RStoolbox 评估分类、变化检测功能的结果一致性。",
    75: "复现 MFC 反应器中电活性生物膜处理含铜酸性矿水的分析结果与菌群多样性可视化。",
    74: "复现使用 haven/labelled 包在 R 数据处理全程保留 SPSS 变量标签的工作流。",
    73: "同 #72，小组另一成员提交版本。",
    72: "复现伽马能谱法田间土壤含水量监测剖面与校准方程预测时间序列。",
    71: "复现细菌丰富度增强土壤有机质热稳定性的 Python 分析与可视化。",
    70: "复现灌溉农业全球能源消耗与碳排放的核心统计图表。",
    68: "同 #106，小组另一成员提交的种子防御策略复现版本。",
    67: "复现全球草地土壤净氮矿化的热图、回归分析与结构方程模型 (SEM)。",
    66: "复现堆肥处理对半干旱冬小麦土壤有机碳、微生物量碳和酶活性的持续效应图表。",
    65: "评估使用扩散先验进行图像特征反演的方法在作物表型信息保留中的应用。",
    64: "评估 Python 包 nrt 的五种卫星图像时间序列监测算法 (EWMA, CCDC 等) 的可复现性。",
    62: "基于 NCBI 宏基因组数据，复现中国南方矿区病毒群落的生物地理分布与驱动因子分析。",
    61: "对比随机森林、克里格和 RFRK 模型预测县域土壤属性空间分布的能力。",
    60: "基于公开共享单车数据集，使用 Python 完成探索性分析与线性回归预测。",
    59: "基于 Zenodo 数据集使用 R Markdown 和 Python 评估磷酸盐肥料的农学效率。",
    58: "同 #92，小组另一成员提交的藻类胞外聚合物提取复现版本。",
    57: "对比线性回归、决策树、随机森林和 LightGBM 模型的 SHAP/LIME 可解释性分析。",
    56: "复现磁性复合载体固定化耐受菌株对土壤镉的吸附实验数据处理与可视化。",
    55: "复现全球尺度氮添加对微生物碳利用效率 (CUE) 影响的空间分布图。",
    54: "使用 GAM 交叉验证模型复现恢复湿地甲烷通量的统计建模与可视化。",
    53: "复现三峡库区经济林恢复对土壤物理质量影响的关键图表 (SPF1-4 与 SPQI)。",
    52: "复现 CO2 提升水分利用效率由水分损耗减少主导而非光合作用增强的核心图表。",
    51: "同 #103，小组另一成员提交的中国土壤数据集复现版本。",
    50: "复现线虫高通量毒性筛选研究的数据分析与可视化结果。",
    49: "复现热带气旋降雨向内陆延伸的核心图表，使用 Python 完成数据分析与可视化。",
    48: "复现温度-深度时间序列反演饱和带土壤水分垂直通量试验。",
    47: "复现基于机器学习的农业肥料推荐系统，使用 Python 完成训练与评估。",
    46: "复现基于深度学习的植物病害检测在智慧农业中的应用。",
    45: "复现 2020 年全球主粮四作物蓝绿水消耗的 CropGBWater 项目核心分析。",
    44: "复现济州岛柑橘园数字孪生的个性化农业潜力分析。",
    43: "复现长期氮磷添加对湿地土壤与植物根际微生物多样性影响的关系图。",
    42: "评估 SuperCC 框架在微生物群落工程与除草剂生物修复中的可重复性。",
    41: "复现人为气候变化降低全球固氮生物多样性的 Nature Communications 论文核心图表。",
    40: "复现土壤养分与作物产量关系的 soiltestcorr R 包核心分析图表。",
    39: "评估首个农业领域中文大语言模型 AgriGPTs 的代码、模型与推理流程可复现性。",
    38: "复现全球水稻多类分割数据集 RiceSEG 的核心分析流程。",
    37: "同 #99，小组另一成员提交的土壤有机碳分子权衡复现版本。",
    36: "复现微生物群落协同生长驱动多稳态形成的 Nature Communications 论文图表。",
    35: "复现农业面源污染 K-Means 聚类与多元回归分析。",
    34: "同 #72，小组另一成员提交的伽马能谱法土壤含水量复现版本。",
    33: "复现 Nature Food 全球耕地氮损失优化管理的核心图表 (Figure 1-3)。",
    32: "复现地中海橄榄园土壤侵蚀综述论文中 Zenodo 公开数据的分析图表。",
    31: "评估 DeepHighlight 项目的可重复性，涵盖深度学习图像分析流程。",
    30: "复现基于机器学习的作物推荐系统完整分析流程。",
    29: "复现中国沿海泥滩潮间带病毒多样性的核心分析与可视化。",
    28: "评估 SoilGrids250m 全球土壤属性栅格数据集的可重复性。",
    27: "复现基于像素集编码器与时间自注意力 (PSE-TAE) 的遥感影像分类模型。",
    26: "复现基于无人机多光谱与点云数据的植被 LAI 和 faPAR 估算方法。",
    25: "复现基于机器学习的环境监测散点密度图与统计验证效果。",
    24: "复现基于深度残差网络与 SAR-光学融合的 Sentinel-2 云去除方法。",
    23: "复现枯萎病根际微生物组通用变异规律的 Nature Communications 论文图表。",
    22: "复现自动流域划分算法 (AOR) 的核心分析流程。",
    21: "复现秸秆还田土壤碳库 Meta 分析的响应比计算与核心图表。",
    20: "复现多尺度下物种入侵悖论的 Meta 分析结果。",
    19: "复现早餐生物废弃物转化为储氢材料的 R 数据分析与可视化。",
    18: "复现凋落物分解主场效应 (HFA) 的核心统计分析。",
    17: "同 #91，小组另一成员提交的多年冻土矿物-酶相互作用复现版本。",
    16: "复现全球 30 米分辨率土壤信息数据库 OpenLandMap 的机器学习建模框架。",
    15: "复现 Konza 草原火烧实验的生态阈值与干扰数据分析。",
    14: "复现基于点注释的大豆种子定位与计数 P2PNet 模型。",
    13: "复现人为气候变化降低全球固氮生物多样性论文的核心图表。",
    12: "使用 R+renv 完成鸢尾花数据集的描述性统计与可视化分析。",
    11: "评估 PlantCV 植物表型与营养数据分析开源项目的可重复性。",
    10: "评估高寒矿区土壤微生物肥料研究的 Network Analysis 代码可复现性。",
    9:  "复现滦河流域径流变化主控因子的 SWAT + XGBoost/RF 分析。",
    8:  "复现 Kaggle 空气质量公开数据集的完整分析流程与 Quarto 报告。",
    7:  "复现基于 Transformer 自监督预训练的遥感时序分类 (SATP) 模型。",
    6:  "复现基于 OpenLandMap SoilSamples 的土壤有机碳空间分布制图。",
    5:  "复现水培大豆营养实验的 ANOVA 分析与可视化。",
    4:  "复现基于 YOLOv8 的实时目标识别。",
    3:  "复现 RadEro 模型估算土壤 137Cs 重分布速率的示例分析。",
    2:  "复现 MediaPipe 人体手指关键点检测。",
    1:  "复现植物多样性对作物产量影响的 Meta 分析与 SEM 路径模型。",
}

# ══════════════════════════════════════════════════════════════════════════════
# 5. Categorise
# ══════════════════════════════════════════════════════════════════════════════
KW = {
    'soil':  ['土壤','碳','氮','有机质','冻土','permafrost','SOC','Soil','侵蚀',
              '水分','水文','流域','径流','湿地','wetland','SoilGrids','OpenLandMap',
              '数字土壤','制图','RadEro','水分利用','水利用','土壤属性','SOC'],
    'plant': ['作物','水稻','小麦','大豆','烟草','柑橘','种子','植物','crop',
              'rice','soybean','wheat','施肥','肥料','产量','凋落物','litter',
              '堆肥','compost','水培','农业','agri','Agri','橄榄','番茄'],
    'env':   ['环境','污染','矿山','废水','病毒','virus','甲烷','methane',
              '空气','cyclone','气旋','气候','climate','镉','吸附','biofilm',
              '碳排放','能源','酸性','矿水'],
    'micro': ['微生物','microb','菌','bacteria','RNA','seq','宏基因','病毒组',
              'virome','根际','rhizo','nitrogen','nematode','线虫','合成菌群',
              'SynCom','node2vec','多稳态','协同生长','固氮'],
    'data':  ['机器学习','深度学习','YOLO','MediaPipe','人脸识别','卫星',
              'Sentinel','无人机','UAV','遥感','RStoolbox','nrt','Transformer',
              'Mamba','分割','PSE-TAE','AgriGPT','GPT','Diffusion',
              'DeepHighlight','鸢尾花','单车','bike','数据','预测','SAR',
              '点云','关键点','检测','P2PNet','Crop','推荐','机器学习'],
}

def categorise(p):
    text = (p['title'] + ' ' + DESC.get(p['num'], '')).lower()
    scores = {c: sum(1 for kw in kws if kw.lower() in text) for c, kws in KW.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'data'

for p in unique:
    p['cat'] = categorise(p)

# ══════════════════════════════════════════════════════════════════════════════
# 6. Detect tools
# ══════════════════════════════════════════════════════════════════════════════
def detect_tools(p):
    text = p['title'] + ' ' + DESC.get(p['num'], '') + ' ' + p['body'][:300]
    tools = []
    if re.search(r'(?:R 语言|Rstudio|R Markdown|renv|ggplot|quarto|R 4\.\d)', text, re.I):
        tools.append('R')
    if re.search(r'Python|PyTorch|pip|conda|Jupyter|Notebook|uv\b', text, re.I):
        tools.append('Python')
    if not tools:
        tools = ['R']
    return tools

# ══════════════════════════════════════════════════════════════════════════════
# 7. Icons
# ══════════════════════════════════════════════════════════════════════════════
ICONS = {
    'soil':  ['🌍','🏔️','❄️','🌱','🗺️','📡','🔬','🏞️'],
    'plant': ['🌾','🌰','🍊','🫘','🍃','🧪','🌱','🌿'],
    'env':   ['⚗️','🧲','🌊','🐜','🔬','🌊'],
    'micro': ['🧬','🦠','🧫','🌿'],
    'data':  ['📊','🛰️','🥭','👤','🚲','📋','🤖'],
}
_cnt = {c: 0 for c in ICONS}
def icon(c):
    i = _cnt[c] % len(ICONS[c]); _cnt[c] += 1; return ICONS[c][i]

# ══════════════════════════════════════════════════════════════════════════════
# 8. Build cards
# ══════════════════════════════════════════════════════════════════════════════
def member_html(m):
    """Render a single member chip."""
    e = E.escape
    name = e(m['name'])
    gh = m.get('gh')
    cls = 'leader' if m['leader'] else 'member'
    star = '★ ' if m['leader'] else ''
    if gh:
        link = f'<a href="https://github.com/{e(gh)}" target="_blank" rel="noopener" class="mlink {cls}" title="@{e(gh)}">{star}{name}</a>'
    else:
        link = f'<span class="mlink {cls}">{star}{name}</span>'
    return link

cards_html = ''
for p in unique:
    cat = p['cat']
    e = E.escape
    desc = DESC.get(p['num'], p['title'])
    title_short = e(p['title'][:72])
    desc_esc = e(desc)
    repo = f"https://github.com/{p['repo']}" if p.get('repo') else f"https://github.com/D2RS-2026spring/projects/issues/{p['num']}"
    issue = f"https://github.com/D2RS-2026spring/projects/issues/{p['num']}"

    # Tool tags
    tools = detect_tools(p)
    tags = ''.join(f'<span class="tag {"r" if t=="R" else "py"}">{t}</span>' for t in tools)

    # Members HTML
    members_html = ''.join(member_html(m) for m in p['members'])

    # DOI
    doi_html = ''
    if p.get('doi'):
        doi_html = f'<a class="clink doi" href="https://doi.org/{e(p["doi"])}" target="_blank" rel="noopener">DOI</a>'

    # Transfer warning
    transfer_warn = ''
    if not p.get('has_repo', True):
        transfer_warn = '<div class="transfer-warn transfer-no-repo">⚠ 未提供 GitHub 仓库链接</div>'
    elif not p.get('transferred', True) and p.get('is_student_repo', False):
        transfer_warn = '<div class="transfer-warn">⚠ 仓库尚未移交到 D2RS-2026spring 组织</div>'

    cards_html += f'''
    <div class="card cat-{cat}" data-cat="{cat}">
      <div class="card-top">
        <div class="card-icon">{icon(cat)}</div>
        <div class="info"><div class="title">{title_short}</div></div>
      </div>
      <div class="tags">{tags}</div>
      <div class="card-body"><div class="desc">{desc_esc}</div></div>
      <div class="card-mem">{members_html}</div>
      {transfer_warn}
      <div class="card-foot">
        <div class="clinks">
          {doi_html}
          <a class="clink" href="{repo}" target="_blank" rel="noopener">
            <svg viewBox="0 0 16 16"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>
            仓库
          </a>
        </div>
        <a class="clink issue" href="{issue}" target="_blank" rel="noopener">Issue #{p["num"]}</a>
      </div>
    </div>'''

# ══════════════════════════════════════════════════════════════════════════════
# 9. Not-submitted table
# ══════════════════════════════════════════════════════════════════════════════
not_sub = json.load(open('/tmp/not_submitted_final.json'))
ns_rows = ''
for sid in sorted(not_sub):
    name = E.escape(not_sub[sid])
    gh = id_to_github.get(sid)
    gh_cell = f'<a href="https://github.com/{E.escape(gh)}" target="_blank">@{E.escape(gh)}</a>' if gh else '—'
    ns_rows += f'<tr><td>{sid}</td><td>{name}</td><td>{gh_cell}</td></tr>\n'

# ══════════════════════════════════════════════════════════════════════════════
# 10. Stats
# ══════════════════════════════════════════════════════════════════════════════
all_names = set()
for p in unique:
    for m in p['members']:
        all_names.add(m['name'])

# ══════════════════════════════════════════════════════════════════════════════
# 11. Shared CSS, nav, footer (non-f-strings — no brace escaping needed)
# ══════════════════════════════════════════════════════════════════════════════
CSS = r'''@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');
:root{--pri:#1a5276;--pri-l:#2980b9;--acc:#27ae60;--gold:#f39c12;--bg:#f8f9fa;--card:#fff;--txt:#2c3e50;--txt2:#636e72;--bdr:#e0e6ed;--shd:0 2px 12px rgba(0,0,0,.08);--r:12px}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Noto Sans SC',system-ui,sans-serif;background:var(--bg);color:var(--txt);line-height:1.6}

.hero{background:linear-gradient(135deg,#1a5276 0%,#2980b9 50%,#1abc9c 100%);color:#fff;padding:68px 24px 52px;text-align:center;position:relative;overflow:hidden}
.hero::before{content:'';position:absolute;inset:-50%;width:200%;height:200%;background:radial-gradient(circle at 30% 50%,rgba(255,255,255,.08) 0%,transparent 50%);pointer-events:none}
.hero h1{font-size:clamp(1.7rem,4vw,2.5rem);font-weight:700;margin-bottom:8px;letter-spacing:1px}
.hero .sub{font-size:clamp(.9rem,1.8vw,1.05rem);font-weight:300;opacity:.92;max-width:680px;margin:0 auto 18px}
.hero .badges{display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:14px}
.hero .badge{background:rgba(255,255,255,.18);backdrop-filter:blur(4px);border:1px solid rgba(255,255,255,.25);padding:5px 14px;border-radius:18px;font-size:.78rem;font-weight:500}

.nav{display:flex;justify-content:center;gap:4px;padding:0;background:#fff;border-bottom:1px solid var(--bdr);flex-wrap:wrap}
.nav a{padding:10px 18px;font-size:.84rem;color:var(--txt2);text-decoration:none;border-bottom:2px solid transparent;transition:all .2s;white-space:nowrap}
.nav a:hover{color:var(--pri)}
.nav a.on{color:var(--pri);font-weight:600;border-bottom-color:var(--pri)}

.stats{display:flex;justify-content:center;gap:44px;padding:22px;background:#fff;border-bottom:1px solid var(--bdr);flex-wrap:wrap}
.stat .n{font-size:1.6rem;font-weight:700;color:var(--pri)}.stat .l{font-size:.78rem;color:var(--txt2);margin-top:2px}

.fb{max-width:1200px;margin:26px auto 0;padding:0 20px;display:flex;gap:8px;flex-wrap:wrap;justify-content:center}
.fbtn{border:1.5px solid var(--bdr);background:#fff;color:var(--txt2);padding:6px 16px;border-radius:18px;cursor:pointer;font-size:.82rem;font-family:inherit;transition:all .2s}
.fbtn:hover{border-color:var(--pri-l);color:var(--pri)}.fbtn.on{background:var(--pri);color:#fff;border-color:var(--pri)}

.ctn{max-width:1200px;margin:22px auto 48px;padding:0 20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px}

.card{background:var(--card);border:1px solid var(--bdr);border-radius:var(--r);box-shadow:var(--shd);overflow:hidden;transition:transform .18s,box-shadow .18s;display:flex;flex-direction:column}
.card:hover{transform:translateY(-3px);box-shadow:0 6px 20px rgba(0,0,0,.12)}
.card-top{padding:16px 16px 0;display:flex;align-items:flex-start;gap:10px}
.card-icon{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;font-size:1.15rem;flex-shrink:0;color:#fff}
.card-top .info{flex:1;min-width:0}
.card-top .title{font-size:.9rem;font-weight:700;color:var(--txt);display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;line-height:1.35}

.tags{display:flex;gap:5px;flex-wrap:wrap;padding:0 16px 8px}
.tag{font-size:.68rem;padding:2px 8px;border-radius:10px;background:#eaf4fc;color:var(--pri-l);font-weight:500}
.tag.r{background:#eaf7ed;color:#27ae60}.tag.py{background:#fef3e2;color:#e67e22}

.card-body{padding:0 16px 10px;flex:1}
.card-body .desc{font-size:.8rem;color:var(--txt2);display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden;line-height:1.5}

.card-mem{padding:0 16px 10px;display:flex;flex-wrap:wrap;gap:4px 8px}
.mlink{font-size:.74rem;text-decoration:none;border-radius:10px;padding:2px 8px;transition:background .15s;white-space:nowrap}
.mlink.leader{background:#fef9e7;color:#b7950b;font-weight:600;border:1px solid #f9e79f}
.mlink.leader:hover{background:#fdebd0}
.mlink.member{background:#eaf2f8;color:#2c3e50;border:1px solid transparent}
.mlink.member:hover{background:#d6eaf8;border-color:#aed6f1}

.transfer-warn{margin:0 16px;padding:6px 12px;background:#fff3cd;border:1px solid #ffc107;border-radius:6px;font-size:.76rem;color:#856404;font-weight:500}
.transfer-no-repo{background:#f8d7da;border-color:#f5c6cb;color:#721c24}

.card-foot{padding:8px 16px 12px;border-top:1px solid var(--bdr);display:flex;align-items:center;justify-content:space-between;gap:6px}
.clinks{display:flex;gap:8px;align-items:center}
.clink{display:inline-flex;align-items:center;gap:3px;font-size:.74rem;color:var(--pri-l);text-decoration:none;font-weight:500;white-space:nowrap;transition:color .15s}
.clink:hover{color:var(--acc)}.clink.doi{color:#e67e22;font-weight:600}.clink.doi:hover{color:#d35400}
.clink.issue{color:var(--txt2);font-weight:400}.clink.issue:hover{color:var(--pri)}
.clink svg{width:13px;height:13px;fill:currentColor}

.cat-soil .card-icon{background:#8d6e63}.cat-plant .card-icon{background:#66bb6a}.cat-env .card-icon{background:#42a5f5}.cat-micro .card-icon{background:#ab47bc}.cat-data .card-icon{background:#ef5350}

.reminder{padding:12px 16px;background:#fff3cd;border:1px solid #ffc107;border-radius:8px;font-size:.86rem;color:#856404;margin-bottom:16px;line-height:1.5}.reminder a{color:#856404;font-weight:600}
.reminder-danger{padding:12px 16px;background:#f8d7da;border:1px solid #f5c6cb;border-radius:8px;font-size:.86rem;color:#721c24;margin-bottom:16px;line-height:1.5}.reminder-danger a{color:#721c24;font-weight:600}
.ns{max-width:1200px;margin:0 auto 48px;padding:0 20px}
.ns h2{font-size:1.05rem;color:var(--pri);margin-bottom:10px;padding-bottom:8px;border-bottom:2px solid var(--pri-l)}
.ns-tbl{width:100%;border-collapse:collapse;font-size:.84rem}.ns-tbl th{background:#f0f4f8;padding:7px 12px;text-align:left;font-weight:600;border-bottom:2px solid var(--bdr)}.ns-tbl td{padding:6px 12px;border-bottom:1px solid var(--bdr)}.ns-tbl tr:hover td{background:#f8f9fa}
.ns-tbl a{color:var(--pri-l);text-decoration:none}.ns-tbl a:hover{text-decoration:underline}
.ns-tbl .col-num{width:60px}.ns-tbl .col-status{width:120px}

footer{text-align:center;padding:26px 20px;font-size:.78rem;color:var(--txt2);border-top:1px solid var(--bdr);background:#fff}footer a{color:var(--pri-l);text-decoration:none}

@media(max-width:600px){.hero{padding:44px 16px 32px}.grid{grid-template-columns:1fr}.stats{gap:18px}.stat .n{font-size:1.3rem}.nav a{padding:8px 12px;font-size:.8rem}}
'''

def nav(active):
    """Navigation bar. active: 'main', 'submitted', 'pending', 'not_submitted'."""
    links = [
        ('main', '主页', 'index.html'),
        ('submitted', '已提交项目', 'submitted.html'),
        ('pending', '待提交项目', 'pending.html'),
        ('not_submitted', '未提交名单', 'not_submitted.html'),
    ]
    items = ''.join(
        f'<a href="{href}" class="{"on" if k == active else ""}">{label}</a>'
        for k, label, href in links)
    return f'<nav class="nav">{items}</nav>'

FOOTER = f'''<footer>
  <p>D2RS 2026 Spring — 数据驱动的可重复性研究 &copy; 2026</p>
  <p style="margin-top:5px"><a href="https://github.com/D2RS-2026spring/projects" target="_blank">GitHub 项目主页</a> &nbsp;|&nbsp; <a href="https://github.com/D2RS-2026spring" target="_blank">课程组织</a></p>
  <p style="margin-top:5px;color:#aaa">页面更新于 {UPDATE_TIME}</p>
</footer>'''

def wrap(title, body_inner):
    """Wrap content in full HTML page with shared CSS and footer."""
    return f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{E.escape(title)}</title>
<style>
{CSS}
</style>
</head>
<body>
{body_inner}
{FOOTER}
</body>
</html>'''

# ══════════════════════════════════════════════════════════════════════════════
# 12. Page 1: Main showcase (index.html)
# ══════════════════════════════════════════════════════════════════════════════
stats_html = f'''
<div class="stats">
  <div class="stat"><div class="n">{len(students)}</div><div class="l">课程总人数</div></div>
  <div class="stat"><div class="n">{len(issues)}</div><div class="l">总项目（Issue）</div></div>
  <div class="stat"><div class="n">{len(all_names)}</div><div class="l">已发现结课作业人数</div></div>
  <div class="stat"><div class="n">{len(unique)}</div><div class="l">已注册项目</div></div>
  <div class="stat"><div class="n">{submitted_count}</div><div class="l">已提交项目</div></div>
</div>'''

reminders = ''
if not_sub:
    reminders += f'<div class="reminder"><strong>⚠ 未提交：</strong>{len(not_sub)} 位同学尚未提交结课作业，详见 <a href="not_submitted.html">未提交名单</a></div>\n'
if no_repo or need_transfer:
    reminders += f'<div class="reminder-danger"><strong>⚠ 待处理：</strong>{len(no_repo)} 个项目未提供仓库链接，{len(need_transfer)} 个项目的仓库仍在个人账号下，详见 <a href="pending.html">待提交项目</a></div>\n'

index_body = f'''
<section class="hero">
  <h1>数据驱动的可重复性研究</h1>
  <p class="sub">Data Driven Reproducible Study (D2RS) — 2026 春季学期<br>学生结课作品展示</p>
  <div class="badges">
    <span class="badge">Quarto 文学化编程</span>
    <span class="badge">可重复性研究</span>
    <span class="badge">科学论文复现</span>
    <span class="badge">开放科学</span>
  </div>
</section>
{nav('main')}
{stats_html}
<div class="fb" id="fb">
  <button class="fbtn on" data-f="all">全部</button>
  <button class="fbtn" data-f="soil">土壤与生态</button>
  <button class="fbtn" data-f="plant">农业与植物</button>
  <button class="fbtn" data-f="env">环境科学</button>
  <button class="fbtn" data-f="micro">微生物与生物信息</button>
  <button class="fbtn" data-f="data">数据科学与遥感</button>
</div>
<div class="ctn">
  {reminders}
  <div class="grid" id="g">
{cards_html}
  </div>
</div>
<script>
document.getElementById('fb').addEventListener('click',e=>{{
  const b=e.target.closest('.fbtn');if(!b)return;
  document.querySelectorAll('.fbtn').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  const f=b.dataset.f;
  document.querySelectorAll('.card').forEach(c=>{{
    c.style.display=(f==='all'||c.dataset.cat===f)?'':'none';
  }});
}});
</script>'''

# ══════════════════════════════════════════════════════════════════════════════
# 13. Page 2: Not-submitted students (not_submitted.html)
# ══════════════════════════════════════════════════════════════════════════════
ns_body = f'''
<section class="hero" style="padding:40px 24px 32px">
  <h1>尚未提交作业的同学</h1>
  <p class="sub">共 {len(not_sub)} 位同学尚未在 projects 仓库中提交结课作业 issue</p>
</section>
{nav('not_submitted')}
{stats_html}
<div class="ns">
  <div class="reminder">
    <strong>⚠ 提醒：</strong>以下同学尚未在 <a href="https://github.com/D2RS-2026spring/projects/issues" target="_blank">projects 仓库</a> 中提交结课作业 issue，请尽快提交。
  </div>
  <table class="ns-tbl">
    <thead><tr><th>学号</th><th>姓名</th><th>GitHub</th></tr></thead>
    <tbody>{ns_rows}</tbody>
  </table>
</div>'''

# ══════════════════════════════════════════════════════════════════════════════
# 14. Page 3: Submitted projects (submitted.html)
# ══════════════════════════════════════════════════════════════════════════════
sub_rows = ''
for p in submitted:
    e = E.escape
    title = e(p['title'][:60])
    members = ', '.join(f'{"★ " if m["leader"] else ""}{e(m["name"])}' for m in p['members'])
    repo_link = f'<a href="https://github.com/{e(p["repo"])}" target="_blank">{e(p["repo"].split("/")[1])}</a>'
    doi_link = f'<a href="https://doi.org/{e(p["doi"])}" target="_blank">DOI</a>' if p.get('doi') else '—'
    issue_link = f'<a href="https://github.com/D2RS-2026spring/projects/issues/{p["num"]}" target="_blank">#{p["num"]}</a>'
    sub_rows += f'<tr><td class="col-num">{issue_link}</td><td>{title}</td><td style="font-size:.78rem">{members}</td><td>{repo_link}</td><td>{doi_link}</td></tr>\n'

submitted_body = f'''
<section class="hero" style="padding:40px 24px 32px">
  <h1>已提交项目</h1>
  <p class="sub">共 {submitted_count} 个项目已成功提交到 D2RS-2026spring 组织</p>
</section>
{nav('submitted')}
{stats_html}
<div class="ns">
  <table class="ns-tbl">
    <thead><tr><th class="col-num">Issue</th><th>项目名称</th><th>小组成员</th><th>仓库</th><th>DOI</th></tr></thead>
    <tbody>{sub_rows}</tbody>
  </table>
</div>'''

# ══════════════════════════════════════════════════════════════════════════════
# 15. Page 4: Pending projects (pending.html)
# ══════════════════════════════════════════════════════════════════════════════
nr_rows = ''
for p in no_repo:
    e = E.escape
    title = e(p['title'][:60])
    members = ', '.join(f'{"★ " if m["leader"] else ""}{e(m["name"])}' for m in p['members'])
    issue_link = f'<a href="https://github.com/D2RS-2026spring/projects/issues/{p["num"]}" target="_blank">#{p["num"]}</a>'
    nr_rows += f'<tr><td class="col-num">{issue_link}</td><td>{title}</td><td style="font-size:.78rem">{members}</td></tr>\n'

nt_rows = ''
for p in need_transfer:
    e = E.escape
    title = e(p['title'][:60])
    members = ', '.join(f'{"★ " if m["leader"] else ""}{e(m["name"])}' for m in p['members'])
    repo_link = f'<a href="https://github.com/{e(p["repo"])}" target="_blank">{e(p["repo"])}</a>'
    issue_link = f'<a href="https://github.com/D2RS-2026spring/projects/issues/{p["num"]}" target="_blank">#{p["num"]}</a>'
    nt_rows += f'<tr><td class="col-num">{issue_link}</td><td>{title}</td><td style="font-size:.78rem">{members}</td><td>{repo_link}</td></tr>\n'

pending_body = f'''
<section class="hero" style="padding:40px 24px 32px">
  <h1>待提交项目</h1>
  <p class="sub">以下项目尚未完成提交，请尽快处理</p>
</section>
{nav('pending')}
{stats_html}
<div class="ns">
  <div class="reminder-danger">
    <strong>⚠ 未提供仓库链接：</strong>以下 {len(no_repo)} 个项目在注册时未提供 GitHub 仓库链接，请尽快补充。
  </div>
  <table class="ns-tbl">
    <thead><tr><th class="col-num">Issue</th><th>项目名称</th><th>小组成员</th></tr></thead>
    <tbody>{nr_rows}</tbody>
  </table>

  <div class="reminder" style="margin-top:32px">
    <strong>⚠ 仓库未移交：</strong>以下 {len(need_transfer)} 个项目的仓库仍在个人账号下，请尽快移交到 <a href="https://github.com/D2RS-2026spring" target="_blank">D2RS-2026spring 组织</a>。
  </div>
  <table class="ns-tbl">
    <thead><tr><th class="col-num">Issue</th><th>项目名称</th><th>小组成员</th><th>当前仓库</th></tr></thead>
    <tbody>{nt_rows}</tbody>
  </table>
</div>'''

# ══════════════════════════════════════════════════════════════════════════════
# 16. Write files
# ══════════════════════════════════════════════════════════════════════════════
BASE = '/Users/gaoch/GitHub/D2RS-2026spring/projects'

with open(f'{BASE}/index.html', 'w') as f:
    f.write(wrap('D2RS 2026 春季 — 结课作品展', index_body))

with open(f'{BASE}/not_submitted.html', 'w') as f:
    f.write(wrap('D2RS 2026 — 未提交名单', ns_body))

with open(f'{BASE}/submitted.html', 'w') as f:
    f.write(wrap('D2RS 2026 — 已提交项目', submitted_body))

with open(f'{BASE}/pending.html', 'w') as f:
    f.write(wrap('D2RS 2026 — 待提交项目', pending_body))

cats = {}
for p in unique:
    cats[p['cat']] = cats.get(p['cat'], 0) + 1
print(f"✅ {len(unique)} projects | {len(all_names)} students")
print(f"   Pages: index.html, submitted.html, pending.html, not_submitted.html")
for c, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"   {c}: {n}")
