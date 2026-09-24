"""补练页面：教师核对题目，学生作答，教师复核反馈。"""
import copy
from uuid import uuid4

import streamlit as st

from campus_practice import (demo_pack, dump_feedback, dump_pack, feedback_rows, generate_pack,
                             load_feedback, load_pack, pack_id, progress, submit, validate_pack)
from campus_ui import explain_error, sources_panel, go


def _new_draft(ctx, pack, signature=None):
    ctx.state['practice_draft'] = {'pack': pack, 'signature': signature, 'editor': uuid4().hex}


def _edit_pack(draft):
    pack = copy.deepcopy(draft['pack'])
    key = 'practice_edit_' + draft['editor']
    st.caption('修改即时保留在本次会话；修改后需重新确认审核，已启用的旧版本保持不变。')
    sources_panel(pack['sources'])
    for i, question in enumerate(pack['questions']):
        with st.expander(f'第{i + 1}题 · ' + ('诊断' if i == 0 else '迁移练习'), expanded=i == 0):
            prefix = key + str(i)
            question['stem'] = st.text_area('题干', question['stem'], key=prefix + 'stem', max_chars=2000)
            for j, option in enumerate(question['options']):
                question['options'][j] = st.text_input('选项' + 'ABCD'[j], option, key=prefix + f'option{j}', max_chars=500)
            question['answer'] = st.selectbox('正确选项', range(4), index=question['answer'],
                                             format_func=lambda index: 'ABCD'[index], key=prefix + 'answer')
            question['hint'] = st.text_area('首次答错后的提示', question['hint'], key=prefix + 'hint', max_chars=1000)
            question['explanation'] = st.text_area('完成后的解析', question['explanation'], key=prefix + 'explanation', max_chars=2000)
            question['references'] = st.multiselect('依据资料', [s['reference'] for s in pack['sources']],
                                                     default=question['references'], key=prefix + 'references')
    return validate_pack(pack)


def teacher_practice(ctx):
    st.subheader('补练与反馈')
    st.write('从学情中选知识点，核对题目后交给学生，再收回作答反馈。')
    active = ctx.state.get('practice_active')
    if active:
        with st.container(border=True):
            st.subheader('已启用练习')
            st.success('已启用：' + active['topic'] + ' · ' + str(len(active['questions'])) + '题')
            st.caption('当前学生作答使用此版本。下方草稿的编辑和审核不会改变此版本，直到你启用新的版本。')
            st.download_button('下载已启用练习包（含答案）', dump_pack(active), 'campus-practice.json',
                               'application/json', key='practice_active_download')
            st.caption('同一会话切换学生端即可作答；其他设备需导入练习包。文件含答案，仅用于自学。')
    result = ctx.state.get('grade_result')
    if result:
        rows = result['report']['知识点']
        topics = [row['知识点'] for row in rows]
        topic = st.selectbox('补练知识点', topics,
                             format_func=lambda value: value + (' · 建议关注' if next(r['需关注'] for r in rows if r['知识点'] == value) else ' · 可巩固'),
                             key='practice_topic_' + ctx.state['grade_fingerprint'])
        st.caption('知识点来自当前学情；演示仅覆盖循环结构，不能代表其他知识点。')
        source_kind = st.radio('题目来源', ['课程资料生成', '合成演示'], horizontal=True, key='practice_source')
        if source_kind == '合成演示':
            st.info('两道循环边界示例题，使用内置合成资料，不调用AI或写入知识库。')
            if st.button('准备循环边界演示题', disabled=topic != '循环结构'):
                _new_draft(ctx, demo_pack(), ctx.state['grade_fingerprint'])
        else:
            from campus_pages import catalog
            data = catalog(ctx)
            documents = [r for r in data['rows'] if r['分类'] == '课程']
            choices = st.multiselect('选择出题资料', [r['id'] for r in documents],
                                     format_func=lambda ident: next(r['来源'] for r in documents if r['id'] == ident),
                                     key='practice_documents')
            if data['error']:
                st.warning('知识库暂时未连接，请到系统设置诊断。')
            elif not documents:
                st.info('请先到教学资料上传课程资料。')
                st.button('前往教学资料', on_click=go, args=('教学资料',), key='practice_upload_link')
            if ctx.config.mode == '离线工具':
                st.caption('当前关闭模型生成；可选合成演示。')
            if st.button('检索资料并生成补练草稿', disabled=not choices or data['error'] or ctx.config.mode == '离线工具'):
                try:
                    with st.spinner('正在检索资料并生成两道待审核题目…'):
                        pack = generate_pack(ctx.knowledge, ctx.config, topic, document_ids=choices)
                    _new_draft(ctx, pack, ctx.state['grade_fingerprint'])
                except Exception as error:
                    explain_error('补练生成', error)
    else:
        st.info('先在学情分析中完成分析，即可按知识点创建补练；也可导入已有练习包审核。')

    with st.expander('导入已有完整练习包'):
        upload = st.file_uploader('选择完整练习包', type=['json'], key='practice_import')
        st.caption('完整包含参考答案，只适合自学练习，不用于保密考试。导入后须重新审核。')
        if st.button('读取练习包待审核', disabled=upload is None):
            try:
                _new_draft(ctx, load_pack(upload.getvalue()))
            except Exception as error:
                explain_error('导入练习', error)

    draft = ctx.state.get('practice_draft')
    if draft:
        st.divider()
        st.subheader('当前草稿 · 教师审核')
        st.write('知识点：' + draft['pack']['topic'] + ' ｜ 来源标记：' + draft['pack']['origin'])
        st.caption('导入包的来源标记由文件提供，不能证明资料真实性。请逐题核对唯一正确答案、提示和原文依据。')
        stale = draft['signature'] is not None and (not result or draft['signature'] != ctx.state.get('grade_fingerprint'))
        if stale:
            st.warning('学情已变化，这份草稿不能作为当前学情的补练启用；请重新生成。')
        try:
            draft['pack'] = _edit_pack(draft)
            ident = pack_id(draft['pack'])
            same_as_active = bool(active and pack_id(active) == ident)
            if same_as_active:
                st.info('这份草稿与已启用版本一致，无需重复启用。练习包可在上方下载。')
            elif active:
                st.info('草稿尚未启用，学生仍使用上方版本。启用新版本会重新开始本次会话的作答记录，请先下载需要保留的反馈。')
            # Keep approval outside widget state: Streamlit discards absent widgets on navigation.
            approved = draft.setdefault('review', {'id': ident, 'confirmed': False})
            if approved['id'] != ident:
                draft['review'] = approved = {'id': ident, 'confirmed': False}
            confirmed = st.checkbox('已核对题目、答案与依据，确认不含个人身份和学校信息',
                                    value=approved['confirmed'], key='practice_confirm_' + ident)
            approved['confirmed'] = confirmed
            if st.button('审核通过，启用补练', type='primary', disabled=not confirmed or stale or same_as_active):
                if ctx.state.get('practice_active_id') != ident:
                    ctx.state['practice_attempts'] = [[], []]
                ctx.state['practice_active'] = copy.deepcopy(draft['pack'])
                ctx.state['practice_active_id'] = ident
                st.rerun()
        except ValueError as error:
            st.error(str(error))

    active = ctx.state.get('practice_active')
    if active:
        st.divider()
        st.subheader('复核作答反馈')
        st.caption('复核对象为已启用版本 ' + pack_id(active)[:12] + '。反馈文件可被编辑，仅供教学参考，不是正式成绩凭证。')
        attempts = ctx.state.get('practice_attempts', [[], []])
        st.write('本次会话作答')
        st.dataframe(feedback_rows(active, attempts), hide_index=True, width='stretch')
        feedback = st.file_uploader('导入学生反馈', type=['json'], key='practice_feedback_file')
        if feedback:
            try:
                imported = load_feedback(feedback.getvalue(), active)
                st.write('导入反馈 · 已按本版参考答案重新核算')
                st.dataframe(feedback_rows(active, imported), hide_index=True, width='stretch')
            except ValueError as error:
                st.error(str(error))


def student_practice(ctx):
    with st.expander('接收教师提供的练习包'):
        upload = st.file_uploader('选择教师提供的 JSON 练习包', type=['json'], key='student_pack_upload')
        st.caption('请使用教师提供的文件。练习包含参考答案，仅用于自学；文件本身不能证明已由教师审核。')
        if st.button('接收并开始练习', disabled=upload is None):
            try:
                imported = load_pack(upload.getvalue())
                if pack_id(imported) != ctx.state.get('student_import_id'):
                    ctx.state['student_import_attempts'] = [[], []]
                ctx.state['student_import_pack'] = imported
                ctx.state['student_import_id'] = pack_id(imported)
                st.session_state['student_pack_source'] = '导入的练习'
            except ValueError as error:
                st.error(str(error))
    choices = []
    if ctx.state.get('practice_active'):
        choices.append('教师本次发布')
    if ctx.state.get('student_import_pack'):
        choices.append('导入的练习')
    if not choices:
        st.info('暂时没有可做的练习。请等待教师发布，或在上方接收教师提供的练习包。')
        return
    if st.session_state.get('student_pack_source') not in choices:
        st.session_state['student_pack_source'] = choices[0]
    source = st.radio('练习来源', choices, key='student_pack_source', horizontal=True)
    is_import = source == '导入的练习'
    attempts_key = 'student_import_attempts' if is_import else 'practice_attempts'
    pack = ctx.state.get('student_import_pack' if is_import else 'practice_active')
    if not pack:
        st.info('暂时没有可做的练习，请等待教师发布。')
        return
    ident = pack_id(pack)
    st.subheader(pack['topic'] + ' · 专项补练')
    st.caption('来源：' + pack['origin'] + ' ｜ 自学练习，每题最多两次；记录仅保存在本次会话，请及时下载。')
    attempts = ctx.state.setdefault(attempts_key, [[], []])
    status = progress(pack, attempts)
    for i, (question, outcome) in enumerate(zip(pack['questions'], status)):
        if i and not status[i - 1]['done']:
            st.info('完成第1题后开启第2题迁移练习。')
            break
        with st.container(border=True):
            st.markdown(f'### 第{i + 1}题')
            st.write(question['stem'])
            if outcome['done']:
                for j, option in enumerate(question['options']):
                    st.write('ABCD'[j] + '. ' + option)
                st.write('你的作答：' + ' → '.join('ABCD'[choice] for choice in attempts[i]))
                (st.success if outcome['correct'] else st.warning)('本题答对。' if outcome['correct'] else '两次尝试已结束，请核对解析并向教师反馈疑问。')
                st.write('参考答案：' + 'ABCD'[question['answer']])
                st.write(question['explanation'])
                sources_panel([s for s in pack['sources'] if s['reference'] in question['references']])
            else:
                if outcome['tries']:
                    st.warning('首次作答未正确。提示：' + question['hint'])
                choice = st.radio('选择答案', range(4), index=None,
                                  format_func=lambda value, q=question: 'ABCD'[value] + '. ' + q['options'][value],
                                  key=f'practice_answer_{ident}_{i}_{outcome["tries"]}')
                if st.button('提交本题答案', key=f'practice_submit_{i}', disabled=choice is None):
                    ctx.state[attempts_key] = submit(pack, attempts, i, choice)
                    st.rerun()
    if all(item['done'] for item in status):
        st.success('两道练习已完成。请把反馈交给教师复核；本次表现不等同于知识点掌握程度。')
    st.dataframe(feedback_rows(pack, attempts), hide_index=True, width='stretch')
    st.download_button('下载作答反馈', dump_feedback(pack, attempts), 'campus-practice-feedback.json', 'application/json')
