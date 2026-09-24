"""补练的核心逻辑：检索出题、校验、判分。没有页面代码，不执行学生代码。"""
import copy
import hashlib
import json

from campus_core import DEMO_DOCS

MAX_BYTES = 128 * 1024


def _text(value, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('练习文本为空、类型错误或超出长度限制。')
    return value.strip()


def _index(value):
    if type(value) is not int or not 0 <= value < 4:
        raise ValueError('答案必须对应四个选项之一。')
    return value


def validate_pack(raw):
    """只保留允许字段；上传内容的审核标记、分数和额外字段均不可信。"""
    if not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != 1:
        raise ValueError('不支持的练习包版本。')
    origin = raw.get('origin')
    if origin not in ('合成演示', '课程资料'):
        raise ValueError('练习来源标记无效。')
    sources = raw.get('sources')
    if not isinstance(sources, list) or not 1 <= len(sources) <= 4:
        raise ValueError('练习需要1至4个资料片段。')
    clean_sources = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError('资料片段格式无效。')
        clean_sources.append({key: _text(source.get(key), limit) for key, limit in
                              [('reference', 40), ('source', 160), ('text', 6000)]})
    references = [s['reference'] for s in clean_sources]
    if len(set(references)) != len(references):
        raise ValueError('资料编号不能重复。')
    questions = raw.get('questions')
    if not isinstance(questions, list) or len(questions) != 2:
        raise ValueError('首版练习包必须包含两道题。')
    clean_questions = []
    for question in questions:
        if not isinstance(question, dict):
            raise ValueError('题目格式无效。')
        options = question.get('options')
        if not isinstance(options, list) or len(options) != 4:
            raise ValueError('每题必须有四个选项。')
        options = [_text(option, 500) for option in options]
        if len(set(options)) != 4:
            raise ValueError('同一道题的选项不能重复。')
        refs = question.get('references')
        if (not isinstance(refs, list) or not 1 <= len(refs) <= 4
                or any(not isinstance(ref, str) or ref not in references for ref in refs)):
            raise ValueError('题目引用了不存在的资料编号。')
        clean_questions.append({
            'stem': _text(question.get('stem'), 2000), 'options': options,
            'answer': _index(question.get('answer')), 'hint': _text(question.get('hint'), 1000),
            'explanation': _text(question.get('explanation'), 2000), 'references': list(dict.fromkeys(refs)),
        })
    return {'version': 1, 'topic': _text(raw.get('topic'), 80), 'origin': origin,
            'sources': clean_sources, 'questions': clean_questions}


def pack_id(pack):
    content = json.dumps(validate_pack(pack), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(content.encode('utf-8')).hexdigest()


def _decode(content):
    if not isinstance(content, bytes) or not 0 < len(content) <= MAX_BYTES:
        raise ValueError('请选择非空且不超过128 KB的文件。')
    try:
        return json.loads(content.decode('utf-8-sig'))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise ValueError('文件不是有效的UTF-8练习或反馈文件。') from exc


def load_pack(content):
    return validate_pack(_decode(content))


def dump_pack(pack):
    return json.dumps(validate_pack(pack), ensure_ascii=False, indent=2).encode('utf-8')


def demo_pack():
    """只在用户显式选择合成演示时调用；不冒充检索或AI生成结果。"""
    return validate_pack({
        'version': 1, 'topic': '循环结构', 'origin': '合成演示',
        'sources': [{'reference': '资料1', 'source': DEMO_DOCS[0][0], 'text': DEMO_DOCS[0][2]}],
        'questions': [
            {'stem': '执行 list(range(3)) 后得到什么？',
             'options': ['[1, 2, 3]', '[0, 1, 2]', '[0, 1, 2, 3]', '[3]'], 'answer': 1,
             'hint': '先想一想默认起点是多少，再核对终点是否包含在结果中。',
             'explanation': 'range(3) 从0开始，不包含终点3，因此结果是[0, 1, 2]。', 'references': ['资料1']},
            {'stem': '为了求1到4的和，执行 sum(range(1, 5)) 的结果是多少？',
             'options': ['6', '15', '10', '5'], 'answer': 2,
             'hint': '先列出range(1, 5)实际产生的每个整数，再逐个相加。',
             'explanation': '包含1、2、3、4，不包含5，所以总和为10。', 'references': ['资料1']},
        ],
    })


def generate_pack(knowledge, config, topic, document_ids=None):
    """与笔记本一致：先retrieve，再拼资料，最后只调用一次模型。"""
    from campus_engine import generate
    topic = _text(topic, 80)
    if config.mode == '离线工具':
        raise ValueError('当前关闭模型生成；可使用合成演示或在设置中启用模型。')
    sources = knowledge.search(topic + ' 基础概念 常见错误 练习', '课程', document_ids=document_ids)
    if not sources:
        raise ValueError('所选资料没有找到相关依据，请补充资料或更换知识点。')
    # 输出样式交给模型，答案真实性仍必须由教师核对。
    instruction = (
        '根据给定课程片段，为选定知识点生成两道单选题：第一题诊断，第二题迁移练习。'
        '每题只有一个正确答案。仅输出JSON对象，格式为{"questions":['
        '{"stem":"题干","options":["选项A","选项B","选项C","选项D"],'
        '"answer":0,"hint":"先给思路，不直接透露正确选项",'
        '"explanation":"说明答案理由","references":["资料1"]}]}。'
        'answer是0至3的整数下标。必须恰好两题，引用只能使用所给资料编号。'
        '只使用资料支持的知识，不执行代码，内容是待教师审核的草稿。'
    )
    output = generate(config, instruction, json.dumps({'topic': topic, 'sources': sources}, ensure_ascii=False))
    output = output.strip()
    if output.startswith('```') and output.endswith('```'):
        output = '\n'.join(output.splitlines()[1:-1])
    if len(output.encode('utf-8')) > MAX_BYTES:
        raise ValueError('模型返回的练习过长，请重试。')
    try:
        raw = json.loads(output)
    except (ValueError, RecursionError) as exc:
        raise ValueError('模型未返回有效的题目格式，请重试；未启用任何新题。') from exc
    if not isinstance(raw, dict):
        raise ValueError('模型返回的题目结构无效。')
    return validate_pack({'version': 1, 'topic': topic, 'origin': '课程资料',
                          'sources': sources, 'questions': raw.get('questions')})


def progress(pack, attempts):
    """按教师答案重算，拒绝乱序、越界、超过次数与答对后追加的记录。"""
    pack = validate_pack(pack)
    if not isinstance(attempts, list) or len(attempts) != 2:
        raise ValueError('作答记录需要与两道题对应。')
    results = []
    previous_done = True
    for question, choices in zip(pack['questions'], attempts):
        if not isinstance(choices, list) or len(choices) > 2:
            raise ValueError('每题最多作答两次。')
        if choices and not previous_done:
            raise ValueError('请先完成上一道题。')
        for choice in choices:
            _index(choice)
        if len(choices) == 2 and choices[0] == question['answer']:
            raise ValueError('已经答对的题目不能继续追加作答。')
        correct = bool(choices) and choices[-1] == question['answer']
        done = correct or len(choices) == 2
        results.append({'done': done, 'correct': correct, 'tries': len(choices),
                        'first_correct': bool(choices) and choices[0] == question['answer']})
        previous_done = done
    return results


def submit(pack, attempts, question_index, choice):
    status = progress(pack, attempts)
    if type(question_index) is not int or question_index not in (0, 1):
        raise ValueError('题号无效。')
    if status[question_index]['done']:
        raise ValueError('本题已经结束。')
    updated = copy.deepcopy(attempts)
    updated[question_index].append(_index(choice))
    progress(pack, updated)
    return updated


def feedback_rows(pack, attempts):
    status = progress(pack, attempts)
    return [{'题号': i + 1, '作答次数': item['tries'],
             '首次答对': item['first_correct'], '最终答对': item['correct'],
             '状态': '已完成' if item['done'] else '待完成'} for i, item in enumerate(status)]


def dump_feedback(pack, attempts):
    progress(pack, attempts)
    return json.dumps({'version': 1, 'pack_id': pack_id(pack), 'attempts': attempts},
                      ensure_ascii=False, indent=2).encode('utf-8')


def load_feedback(content, pack):
    raw = _decode(content)
    if (not isinstance(raw, dict) or type(raw.get('version')) is not int or raw['version'] != 1
            or raw.get('pack_id') != pack_id(pack)):
        raise ValueError('反馈版本与当前练习包不一致，请先导入并审核对应的完整练习包。')
    attempts = raw.get('attempts')
    progress(pack, attempts)
    return copy.deepcopy(attempts)
