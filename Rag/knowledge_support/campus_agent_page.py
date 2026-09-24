"""Smart task and skill authoring pages, integrated with the existing campus shell."""
from pathlib import Path
import os
from uuid import uuid4

import streamlit as st

from campus_harness import RunContext, run_task
from campus_skills import SkillLibrary, parse_skill, MAX_SKILL_BYTES
from campus_ui import header, sources_panel

TEMPLATES = {
    '期末复习计划': ('my-review-plan', '用户希望安排期末复习、按天制定学习计划时使用。',
                 '1. 确认科目、剩余天数和每天可用时间，缺少关键信息时先询问。\n'
                 '2. 调用 search_knowledge 查找相关课程材料，记录资料引用。\n'
                 '3. 按天列出目标、复习内容和自测任务，明确区分资料事实与学习建议。\n'
                 '4. 用 save_draft 保存待审核的复习计划。'),
    '错题讲解': ('my-mistake-coach', '用户提供错题并希望获得提示、分析错误原因时使用。',
              '1. 确认题目和用户尝试；题意不完整时先澄清。\n'
              '2. 调用 search_knowledge 查找相关概念。\n'
              '3. 先提供一个关键提示，再解释错误原因，最后给一道同类自测题。\n'
              '4. 引用检索资料，生成题目须注明是练习建议。'),
    '自定义流程': ('my-campus-skill', '描述用户在什么情况下应当使用这个技能。',
                '1. 确认完成任务所需的信息。\n2. 使用合适的校园工具处理任务。\n3. 按用户需要的格式给出结果。'),
}


def _library():
    root = Path(os.getenv('CAMPUS_CONFIG_ROOT', str(Path(__file__).resolve().parent)))
    return SkillLibrary(root, st.session_state.get('campus_role'))


def _role_state(ctx):
    role = st.session_state['campus_role']
    return ctx.state.setdefault('smart_tasks', {}).setdefault(role, {'history': [], 'runs': []})


def _run_error(error):
    # Never render arbitrary provider exceptions: they can contain request URLs or credentials.
    from langgraph.errors import GraphRecursionError
    from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
    from langchain.agents.middleware.tool_call_limit import ToolCallLimitExceededError
    if isinstance(error, (GraphRecursionError, ModelCallLimitExceededError, ToolCallLimitExceededError)):
        return '任务达到执行次数上限，已停止。请拆成更小的任务后重试。'
    if isinstance(error, ImportError):
        return '智能任务依赖未就绪，请在项目 Python 环境安装 requirements.txt 后重启。'
    if isinstance(error, ValueError) and error.__class__ is ValueError:
        # Only our predictable validation messages are suitable for direct presentation.
        safe_starts = ('任务要求须', '补充材料最多', '所选技能', '试运行技能', '智能任务需要', '模型未返回完整', '一次最多启用', '无法加载')
        if str(error).startswith(safe_starts):
            return str(error)
    return '本次任务未完成。请检查模型、知识库连接与配置，或缩小任务范围后重试；不会自动切换模型。'


def _show_result(result, ident):
    for warning in result['warnings']:
        st.warning(warning)
    st.markdown(result['answer'])
    st.caption(f"模型调用 {result['model_calls']} 次 · 已加载技能：{'、'.join(result['loaded_skills']) or '无'}"
               + (f" · Token {result['total_tokens']}" if result['total_tokens'] else ''))
    st.download_button('下载本次回答', result['answer'], '校园智能任务.md', 'text/markdown', key='answer_' + ident)
    for index, draft in enumerate(result['drafts']):
        with st.expander('待审核草稿 · ' + draft['title']):
            st.markdown(draft['content'])
            st.download_button('下载草稿', draft['content'], f'校园草稿-{index + 1}.md',
                               'text/markdown', key=f'draft_{ident}_{index}')
    sources_panel(result['sources'])
    with st.expander('执行记录'):
        for todo in result['todos']:
            status = {'completed': '已完成', 'in_progress': '进行中', 'pending': '待处理'}.get(todo.get('status'), '待处理')
            st.text(f"{status} · {todo.get('content', '')}")
        results = {e['id']: e for e in result['events'] if e['kind'] == 'result'}
        for event in result['events']:
            if event['kind'] == 'call':
                st.text(f"{event['label']} · {results.get(event['id'], {}).get('label', '已发起')} {event['detail']}")


def smart_tasks(ctx):
    header('智能任务', '说出目标，让助手选择技能、查找资料并组织结果。')
    role = st.session_state['campus_role']
    state = _role_state(ctx)
    library = _library()
    skills, errors = library.list()
    for error in errors:
        st.warning(error)
    enabled = [s for s in skills if s.enabled]
    options = ['自动选择'] + [s.name for s in enabled]
    pending = state.pop('try_skill', None)
    select_key = 'smart_skill_' + role
    if pending in options:
        st.session_state[select_key] = pending
    if st.session_state.get(select_key) not in options:
        st.session_state[select_key] = options[0]
    selected = st.selectbox('使用技能', options, key=select_key)
    st.caption('可在“我的技能”中编写自己的流程。任务与参考文本将发送给当前配置的回答模型；检索沿用现有资料处理服务。')
    if ctx.config.mode == '离线工具':
        st.info('当前为离线工具模式。技能仍可编辑；运行智能任务需要在教师端系统设置中启用回答模型。')
    with st.form('smart_task_form_' + role):
        prompt = st.text_area('任务要求', placeholder='例如：结合课程资料，帮我制定三天的 Python 循环复习计划，每天 30 分钟。',
                              max_chars=6000, height=130, key='smart_prompt_' + role)
        with st.expander('补充材料与连续对话'):
            material = st.text_area('参考文本（可选）', max_chars=20000, height=130, key='smart_material_' + role)
            followup = st.checkbox('参考本次会话最近的任务问答', value=False)
        submitted = st.form_submit_button('开始执行', type='primary', disabled=ctx.config.mode == '离线工具')
    if submitted:
        context = RunContext(ctx.knowledge, role, summary=ctx.state.get('grade_result', {}).get('report'))
        emitted = []
        with st.status('正在执行任务…', expanded=True) as status:
            def progress(event):
                emitted.append(event)
                if event['kind'] == 'call':
                    st.write(event['label'] + ('：' + event['detail'] if event['detail'] else ''))
            try:
                chosen = None if selected == '自动选择' else selected
                result = run_task(ctx.config, context, library.snapshot(chosen), prompt,
                                  history=state['history'] if followup else (), material=material,
                                  selected=chosen, on_event=progress)
            except Exception as error:
                status.update(label='本次任务未完成', state='error', expanded=True)
                st.error(_run_error(error))
                state['last_error'] = True
            else:
                status.update(label='任务已完成', state='complete', expanded=False)
                if not followup:
                    state['history'] = []
                state['history'] = (state['history'] + [{'role': 'user', 'content': prompt},
                                    {'role': 'assistant', 'content': result['answer']}])[-6:]
                state['runs'] = (state['runs'] + [{'id': uuid4().hex, 'prompt': prompt, 'result': result}])[-5:]
                state['last_error'] = False
    if state['runs']:
        st.divider()
        st.subheader('最近任务结果' if state.get('last_error') else '任务结果')
        run = state['runs'][-1]
        st.caption('任务：' + run['prompt'][:200])
        _show_result(run['result'], run['id'])
        if len(state['runs']) > 1:
            with st.expander('之前的任务'):
                for old in reversed(state['runs'][:-1]):
                    st.write(old['prompt'][:200])
                    st.markdown(old['result']['answer'])
        if st.button('清空本角色任务记录'):
            state['history'], state['runs'] = [], []
            st.rerun()


def _fill_editor(role, name, description, body, enabled=True, reference=''):
    for field, value in {'name': name, 'description': description, 'body': body,
                         'enabled': enabled, 'reference': reference}.items():
        st.session_state[f'skill_{role}_{field}'] = value


def skill_manager(ctx):
    header('我的技能', '用自然语言定义工作步骤，保存后在智能任务中使用。')
    role = st.session_state['campus_role']
    library = _library()
    skills, errors = library.list()
    st.caption('自定义技能保存在本机，按教师端与学生端分开；同一角色的其他会话也可使用。当前没有账号级私有空间。')
    for error in errors:
        st.warning(error)
    editor_key = 'skill_editor_choice_' + role
    remembered_key = 'skill_editor_remembered_' + role
    choices = ['新建技能'] + [s.name for s in skills]
    if st.session_state.get(editor_key) not in choices:
        remembered = st.session_state.get(remembered_key)
        st.session_state[editor_key] = remembered if remembered in choices else choices[0]
    selected = st.selectbox('选择技能', choices, key=editor_key)
    st.session_state[remembered_key] = selected
    current = next((s for s in skills if s.name == selected), None)
    signature = (role, selected)
    if st.session_state.get('skill_editor_loaded') != signature or f'skill_{role}_name' not in st.session_state:
        values = (current.name, current.description, current.body, current.enabled, current.reference) if current else (*TEMPLATES['期末复习计划'], True, '')
        _fill_editor(role, *values)
        st.session_state['skill_editor_loaded'] = signature
    if current:
        st.caption(current.origin + '技能 · ' + ('已启用' if current.enabled else '已停用'))
        st.download_button('导出 SKILL.md', current.text, 'SKILL.md', 'text/markdown')
        if current.reference:
            st.download_button('导出 reference.md', current.reference, 'reference.md', 'text/markdown')
        if current.enabled and st.button('试运行此技能', type='primary'):
            _role_state(ctx)['try_skill'] = current.name
            st.session_state['workspace_nav'] = '智能任务'
            st.rerun()
    if current and current.origin == '内置':
        st.info('内置技能只读。新建技能时可以粘贴这些步骤并使用自己的技能标识。')
        st.code(current.text, language='markdown')
        return
    with st.expander('从模板或文件开始'):
        template = st.selectbox('技能模板', list(TEMPLATES), key='skill_template_' + role)
        if st.button('填入模板'):
            _fill_editor(role, *TEMPLATES[template])
        upload = st.file_uploader('导入 SKILL.md（先预览，保存后生效）', type=['md'], key='skill_import_' + role)
        if st.button('载入导入文件', disabled=upload is None):
            try:
                if upload.size > MAX_SKILL_BYTES:
                    raise ValueError('SKILL.md 不能超过 24 KB。')
                _fill_editor(role, *parse_skill(upload.getvalue().decode('utf-8-sig')))
            except (ValueError, UnicodeError):
                st.error('导入失败：请检查 UTF-8 编码、name/description 头部和文件大小。')
    if st.session_state.pop('skill_saved_notice', False):
        st.success('技能已保存。下次执行任务时生效。')
    with st.form('skill_edit_form_' + role):
        name = st.text_input('技能标识', key=f'skill_{role}_name', max_chars=48,
                             help='小写英文与连字符，例如 my-review-plan。相同标识会更新已有自定义技能。')
        description = st.text_area('何时使用这个技能', key=f'skill_{role}_description', max_chars=500, height=90)
        body = st.text_area('技能步骤', key=f'skill_{role}_body', max_chars=12000, height=250)
        reference = st.text_area('参考文本（可选）', key=f'skill_{role}_reference', height=110,
                                 help='保存为同目录 reference.md。在步骤中写明需要时读取它；下载分享时同时导出此文件。')
        enabled = st.checkbox('启用此技能', key=f'skill_{role}_enabled')
        save = st.form_submit_button('保存技能', type='primary')
    with st.expander('可用工具说明'):
        st.markdown('`list_documents`：查看资料目录。\n\n`search_knowledge`：检索课程资料（教师也可检索行政资料）。\n\n'
                    '`save_draft`：保存本次任务的待审核草稿。\n\n`read_file`：读取技能与参考文本。\n\n'
                    '`write_todos`：维护执行计划。')
        if role == '教师端':
            st.markdown('`get_learning_summary`：读取学情分析页已完成的汇总统计。')
        st.caption('技能定义如何使用工具；新工具需要在项目代码中接入。')
    if save:
        try:
            library.save(name, description, body, enabled, reference)
        except ValueError as error:
            st.error(str(error))
        except OSError:
            st.error('保存失败，请检查项目 data 目录的写入权限。')
        else:
            st.session_state['skill_saved_notice'] = True
            st.rerun()
