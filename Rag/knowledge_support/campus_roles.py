"""Local role workspaces; role selection is navigation, not authentication."""
import streamlit as st
from campus_ui import header, go, draft_editor

from campus_navigation import PAGES

ROLE_NAV = {role: PAGES.navigation(role) for role in ('教师端', '学生端')}


def enter_role(role):
    st.session_state['campus_role'] = role
    st.session_state['workspace_nav'] = ROLE_NAV[role][0]


def change_role():
    st.session_state.pop('campus_role', None)
    st.session_state.pop('workspace_nav', None)


def select_role():
    header('欢迎使用校园智助', '选择你的身份，进入专属工作区。')
    for col, role, title, detail in zip(
        st.columns(2), ROLE_NAV,
        ['了解学情，准备下一堂课', '解决疑问，完成一次练习'],
        ['分析学情 · 备课出题 · 查看反馈', '课程答疑 · 专项练习 · 学习资料'],
    ):
        with col.container(border=True):
            st.subheader(role)
            st.write(title)
            st.caption(detail)
            st.button('进入' + role, on_click=enter_role, args=(role,), type='primary', width='stretch')
    st.caption('本机演示可切换身份；角色选择不提供账号权限验证。')


def visible_drafts(state, role):
    categories = {'教学', '办公'} if role == '教师端' else {'学习'}
    return [draft for draft in state.get('drafts', []) if draft['category'] in categories]


def role_home(ctx, role):
    teacher = role == '教师端'
    header('教学首页' if teacher else '学习首页',
           '从学情到备课，再到练习反馈。' if teacher else '带着问题学习，通过练习巩固。')
    tasks = ([('学情分析', '查看薄弱知识点'), ('备课与练习', '准备教学与查看反馈'), ('教学资料', '管理课程依据')]
             if teacher else [('课程答疑', '获得有依据的讲解'), ('我的练习', '完成教师提供的练习'), ('我的资料', '上传课件、笔记或题目')])
    for col, (page, detail) in zip(st.columns(3), tasks):
        with col.container(border=True):
            st.subheader(page)
            st.caption(detail)
            st.button('进入' + page, key='home_' + page, on_click=go, args=(page,), width='stretch')
    if teacher:
        report = ctx.state.get('grade_result', {}).get('report')
        if report:
            st.info(f'最近学情：{report["学生数"]} 名匿名学生，{report["记录数"]} 条记录。')
        else:
            st.info('尚未分析学情。可先上传成绩，或使用合成样例。')
        pack = ctx.state.get('practice_active')
        if pack:
            from campus_practice import progress
            outcomes = progress(pack, ctx.state.get('practice_attempts', [[], []]))
            done = sum(item['done'] for item in outcomes)
            st.write(f'已发布练习：{pack["topic"]} · 本次学生作答已完成 {done}/{len(outcomes)} 题')
    else:
        packs = [('教师发布', ctx.state.get('practice_active'), 'practice_attempts'),
                 ('已接收', ctx.state.get('student_import_pack'), 'student_import_attempts')]
        available = [item for item in packs if item[1]]
        if not available:
            st.info('暂无待完成练习。可先进行课程答疑，或在“我的练习”接收教师提供的文件。')
        for label, pack, key in available:
            from campus_practice import progress
            outcomes = progress(pack, ctx.state.get(key, [[], []]))
            done = sum(item['done'] for item in outcomes)
            st.write(f'{label}：{pack["topic"]} · 已完成 {done}/{len(outcomes)} 题')
    st.subheader('教学与办公草稿' if teacher else '我的学习摘录')
    drafts = visible_drafts(ctx.state, role)
    if not drafts:
        st.caption('保存的成果会显示在这里，方便继续编辑和下载。')
        return
    selected = st.selectbox('选择成果', [d['id'] for d in drafts], key='role_drafts_' + role,
                           format_func=lambda ident: next(d['title'] for d in drafts if d['id'] == ident))
    draft_editor(next(d for d in drafts if d['id'] == selected))


def learning_materials(ctx):
    from campus_pages import catalog
    header('学习资料', '选择课程资料，带着具体问题开始学习。')
    data = catalog(ctx)
    if data['error']:
        st.info('资料暂时无法读取，请联系教师检查资料服务。')
        st.button('上传或查看我的资料', on_click=go, args=('我的资料',), type='primary')
        if st.button('重新读取资料'):
            catalog(ctx, True)
            st.rerun()
        return
    courses = [row for row in data['rows'] if row['分类'] == '课程']
    if not courses:
        st.info('教师尚未添加课程资料。可以先上传自己的课件、笔记或题目开始学习。')
        st.button('上传或查看我的资料', on_click=go, args=('我的资料',), type='primary')
        st.button('查看我的练习', on_click=go, args=('我的练习',))
        if st.button('刷新课程资料'):
            catalog(ctx, True)
            st.rerun()
        return
    query = st.text_input('搜索课程资料', placeholder='输入课程或资料名称', key='course_material_query')
    rows = [row for row in courses if query.strip().casefold() in row['来源'].casefold()]
    if not rows:
        st.info('没有找到匹配的课程资料，请更换关键词或清除搜索。')
        st.button('清除搜索', on_click=lambda: st.session_state.update(course_material_query=''))
        return
    st.dataframe([{k: v for k, v in row.items() if k != 'id'} for row in rows], hide_index=True, width='stretch')
    selected = st.selectbox('选择答疑资料', [row['id'] for row in rows],
                           format_func=lambda ident: next(row['来源'] for row in rows if row['id'] == ident))
    def ask_about():
        ctx.state.setdefault('qa_preferences', {}).setdefault('课程', {})['scope'] = selected
        st.session_state.pop('qa_scope_课程', None)
        st.session_state['student_qa_source'] = '课程资料'
        go('课程答疑')
    st.button('围绕这份资料提问', on_click=ask_about, type='primary')


def preparation_page(ctx):
    from campus_pages import teaching_design
    from campus_practice_page import teacher_practice
    header('备课与练习', '准备教学方案，审核练习，复核学生反馈。')
    tasks = {'教学设计': teaching_design, '练习与反馈': teacher_practice}
    task = st.radio('准备任务', list(tasks), key='teacher_prepare', horizontal=True)
    tasks[task](ctx)


def course_answer_page(ctx):
    from functools import partial
    from campus_pages import answer_workspace
    from campus_personal_page import personal_answer
    header('课程答疑', '选择资料，获得讲解或提示，逐步理解问题。')
    sources = {'课程资料': partial(answer_workspace, category='课程'), '我的资料': personal_answer}
    source = st.radio('答疑来源', list(sources), key='student_qa_source', horizontal=True)
    sources[source](ctx)


def practice_page(ctx):
    from campus_practice_page import student_practice
    header('我的练习', '完成练习、查看解析，将作答反馈交给教师。')
    student_practice(ctx)


def render_page(ctx, role, page):
    target = PAGES.resolve(role, page)
    if target is None:
        st.error('当前身份没有此页面入口，请返回首页。')
        return
    target.render(ctx)
