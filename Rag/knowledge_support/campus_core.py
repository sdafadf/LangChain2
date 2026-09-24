"""Local campus skills: validated statistics, SQLite retrieval and safe exports.

No network calls in this module. Student rows are never persisted here.
"""
import csv
import hashlib
import io
import json
import math
import re
import sqlite3
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

FIELDS = ['学生编号', '知识点', '得分', '满分']
DEMO_GRADES = '''学生编号,知识点,得分,满分
S001,循环结构,6,10
S001,条件判断,9,10
S001,函数参数,5,10
S002,循环结构,4,10
S002,条件判断,8,10
S002,函数参数,6,10
S003,循环结构,5,10
S003,条件判断,9,10
S003,函数参数,4,10
S004,循环结构,8,10
S004,条件判断,10,10
S004,函数参数,7,10
'''
DEMO_DOCS = [
    ('Python基础·循环结构（合成课程资料）', '课程',
     'for 循环遍历可迭代对象，while 循环在条件为真时重复执行。range(3) 产生 0、1、2，不含终点 3。'
     'break 终止当前循环，continue 跳过本轮剩余语句。检查循环错误时先列出每轮变量取值。'
     '课堂练习：计算 sum(range(1, 5))，结果为 10。学习建议：先手动跟踪，再运行验证。'),
    ('Python基础·函数参数（合成课程资料）', '课程',
     '函数使用 def 定义；参数在调用时接收输入，return 返回结果。没有 return 的函数返回 None。'
     '位置参数按顺序匹配，关键字参数按名称匹配。默认参数在定义时求值，应避免用可变列表作为默认值。'
     '练习：定义 add(a, b)，用 return a + b 返回两数之和。'),
    ('Python基础·条件判断（合成课程资料）', '课程',
     'if、elif、else 用于条件判断。多个分支按顺序判断，仅执行第一个满足条件的分支。'
     '等于比较使用 ==，赋值使用 =。课堂互动可让学生先预测分支结果，再讨论判断顺序。'),
    ('教学设备借用流程（合成制度，仅用于演示）', '行政',
     '设备借用：申请人提交设备名称、用途、借用时间、归还时间和联系信息；由管理人员核对库存并确认。'
     '材料清单：设备借用申请表、用途说明。领取和归还时记录设备状态。未收到确认前不能视为借用成功。'
     '这份合成制度不代表任何真实单位规定。'),
    ('教室使用申请（合成制度，仅用于演示）', '行政',
     '教室使用申请需提供活动主题、人数、使用时段和设备需求；管理人员确认空闲情况后反馈安排。'
     '材料清单：场地申请表、活动方案。具体办理时限和审批人未在本演示资料中规定，应向管理人员确认。'),
]


def parse_grades(content, allow_duplicates=False):
    """Reject the whole import on invalid rows; never silently discard grades."""
    if not content or len(content) > 2 * 1024 * 1024:
        raise ValueError('请选择非空且不超过 2 MB 的 CSV 文件。')
    try:
        raw = content.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('请将 CSV 保存为 UTF-8 编码。') from exc
    reader = csv.DictReader(io.StringIO(raw))
    if reader.fieldnames != FIELDS:
        raise ValueError('列名和顺序必须为：' + '、'.join(FIELDS) + '。请下载模板；不要上传姓名等额外字段。')
    rows, seen, duplicates = [], set(), 0
    try:
        for line, row in enumerate(reader, 2):
            if len(rows) >= 10000:
                raise ValueError('最多支持 10000 条记录，请拆分文件。')
            if None in row or any(v is None or not v.strip() for v in row.values()):
                raise ValueError(f'第 {line} 行列数不匹配或存在空值。')
            sid, topic = row['学生编号'].strip(), row['知识点'].strip()
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,31}', sid):
                raise ValueError(f'第 {line} 行学生编号须为 S001 等字母开头的匿名编号。')
            if len(topic) > 80 or '\x00' in topic:
                raise ValueError(f'第 {line} 行知识点过长或包含无效字符。')
            try:
                score, maximum = float(row['得分']), float(row['满分'])
            except ValueError as exc:
                raise ValueError(f'第 {line} 行得分和满分必须是数值。') from exc
            if not all(math.isfinite(n) for n in (score, maximum)) or not (0 < maximum <= 1000000 and 0 <= score <= maximum):
                raise ValueError(f'第 {line} 行成绩无效：满分须大于 0 且不超过 1000000，得分须在 0 与满分之间。')
            key = (sid, topic)
            if key in seen:
                duplicates += 1
            seen.add(key)
            rows.append(dict(zip(FIELDS, (sid, topic, score, maximum))))
    except csv.Error as exc:
        raise ValueError('CSV 格式异常，请检查引号和分隔符。') from exc
    if not rows:
        raise ValueError('文件只有表头，没有成绩记录。')
    if duplicates and not allow_duplicates:
        raise ValueError(f'发现 {duplicates} 条重复的学生编号与知识点组合。若为多次作业，请勾选保留全部记录后重新分析。')
    return rows


def analyze_grades(rows, threshold=60):
    if not rows or not 0 <= threshold <= 100:
        raise ValueError('需要成绩记录，阈值必须在 0 至 100 之间。')
    groups = defaultdict(list)
    for row in rows:
        groups[row['知识点']].append(row)
    topics = []
    for topic, items in groups.items():
        rate = 100 * sum(r['得分'] for r in items) / sum(r['满分'] for r in items)
        topics.append({'知识点': topic, '记录数': len(items),
                       '得分率%': round(rate, 2), '需关注': rate < threshold})
    topics.sort(key=lambda r: r['得分率%'])
    return {'学生数': len({r['学生编号'] for r in rows}), '记录数': len(rows),
            '总得分率%': round(100 * sum(r['得分'] for r in rows) / sum(r['满分'] for r in rows), 2),
            '阈值%': threshold, '知识点': topics}


def teaching_plan(report):
    weak = [r['知识点'] for r in report['知识点'] if r['需关注']]
    focus = '、'.join(weak) or '当前各知识点的迁移应用'
    return (f'## 教学建议（本地规则草稿）\n\n'
            f'统计范围：{report["学生数"]} 个匿名学生、{report["记录数"]} 条记录；'
            f'总得分率 {report["总得分率%"]}%。\n\n'
            f'重点复习：{focus}。阈值为 {report["阈值%"]}%，不用于给学生贴标签。\n\n'
            '1. 课前：围绕薄弱项选取两道诊断题，让学生说明思路。\n'
            '2. 课中：先独立作答，再同伴讨论，最后展示典型错误并修正。\n'
            '3. 课后：按错误原因安排基础题与迁移题，依据课程资料答疑。\n'
            '4. 课程迭代：补充易错点示例；用下一次同口径作业复测。\n\n'
            '本建议由确定性规则生成，需教师审核；未调用生成模型。')


def safe_csv(rows, fields):
    """Only export explicitly selected aggregate fields; neutralize spreadsheet formulas."""
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    def cell(value):
        text = str(value)
        return "'" + text if text.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else text
    writer.writerow([cell(f) for f in fields])
    for row in rows:
        writer.writerow([cell(row.get(f, '')) for f in fields])
    return output.getvalue().encode('utf-8-sig')


def redact(text):
    text = re.sub(r'(?<!\d)1[3-9]\d{9}(?!\d)', '[手机号已隐藏]', text)
    text = re.sub(r'(?<!\d)\d{17}[\dXx](?!\d)', '[证件号已隐藏]', text)
    text = re.sub(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}', '[邮箱已隐藏]', text)
    return text


def terms(text):
    text = text.lower()
    result = set(re.findall(r'[a-z0-9_]{2,}', text))
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        result.update(run[i:i+2] for i in range(len(run)-1))
    return result


class LocalKnowledge:
    """SQLite store isolated from the old customer-service Milvus collection."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, source TEXT NOT NULL, category TEXT NOT NULL, text TEXT NOT NULL)')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.path), timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def add(self, source, category, text):
        if category not in ('课程', '行政'):
            raise ValueError('请选择课程或行政资料。')
        if not text.strip() or len(text) > 200000:
            raise ValueError('资料不能为空，最多支持 20 万字符。')
        source = source.replace('\\', '/').rsplit('/', 1)[-1][:150]
        digest = hashlib.sha256((category + '\n' + text).encode()).hexdigest()
        with self.connect() as conn:
            if conn.execute('SELECT 1 FROM documents WHERE id=?', (digest,)).fetchone():
                return False
            size = conn.execute('SELECT COALESCE(SUM(length(text)),0) FROM documents').fetchone()[0]
            if size + len(text) > 5000000:
                raise ValueError('轻量知识库已达 500 万字符上限，请清理资料或使用增强存储。')
            conn.execute('INSERT INTO documents VALUES (?,?,?,?)', (digest, source, category, text))
        return True

    def list(self):
        with self.connect() as conn:
            return [dict(zip(('id', '来源', '分类', '字符数'), row)) for row in
                    conn.execute('SELECT id,source,category,length(text) FROM documents ORDER BY source')]

    def delete(self, document_id):
        with self.connect() as conn:
            conn.execute('DELETE FROM documents WHERE id=?', (document_id,))

    def search(self, query, category, limit=4):
        query_terms = terms(query)
        if not query_terms:
            return []
        with self.connect() as conn:
            docs = conn.execute('SELECT source,text FROM documents WHERE category=?', (category,)).fetchall()
        matches = []
        for source, body in docs:
            for offset in range(0, len(body), 600):
                chunk = body[offset:offset+800]
                shared = query_terms & terms(source + ' ' + chunk)
                if shared:
                    score = len(shared) / len(query_terms)
                    matches.append({'source': source, 'text': chunk, 'score': score})
        matches.sort(key=lambda r: r['score'], reverse=True)
        return [{**r, 'reference': f'资料{i}'} for i, r in enumerate(matches[:limit], 1)]


def office_draft(kind, text):
    """Extract source lines, do not invent owners or deadlines in offline mode."""
    if not text.strip() or len(text) > 20000:
        raise ValueError('请输入 1 至 20000 字的办公原文。')
    if kind == '会议纪要与待办':
        lines = [s.strip() for s in re.split(r'[\n。；]+', text) if s.strip()]
        tasks = [s for s in lines if any(w in s for w in ('负责', '完成', '提交', '准备', '确认', '安排'))]
        return ('## 会议纪要（本地原文整理）\n\n### 原文要点\n' + '\n'.join('- ' + s for s in lines)
                + '\n\n### 待办候选（请核实原文语境）\n'
                + ('\n'.join('- ' + s for s in tasks) or '- 原文未明确待办，待确认。')
                + '\n\n负责人及期限：仅以原文明确表述为准，未明确的项目待确认。\n'
                '此结果为规则提取，未判断提议是否已通过，未调用生成模型。')
    return ('## 通知草稿（待审核）\n\n通知对象：待确认\n\n' + text.strip()
            + '\n\n发布部门：待确认\n发布日期：待确认\n\n'
            '此结果仅规整用户原文，未补造事实，未自动发布。')
