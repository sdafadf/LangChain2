"""Student upload, preview, deletion, and grounded personal-document Q&A."""
import streamlit as st

from campus_embeddings import ProjectEmbedder
from campus_engine import CampusCoordinator
from campus_personal import PersonalKnowledge, PersonalSearch
from campus_ui import header, go, sources_panel, explain_error

SESSION = '仅本次会话'
PERSISTENT = '长期保存'


@st.cache_resource
def persistent_connection(settings, embedding):
    from campus_personal_milvus import StudentMilvus, student_settings
    return StudentMilvus(student_settings(settings), embedding)


def storage_choice(ctx):
    options = [SESSION, PERSISTENT]
    previous = ctx.state.get('personal_storage', SESSION)
    if previous == 'Milvus（长期保存）':
        previous = PERSISTENT
        ctx.state['personal_storage'] = previous
    if st.session_state.get('personal_storage_choice') not in options:
        st.session_state['personal_storage_choice'] = previous if previous in options else SESSION
    mode = st.radio('保存方式', options,
                    key='personal_storage_choice', horizontal=True)
    if mode != previous:
        for key in ('personal_file_select', 'personal_qa_select'):
            st.session_state.pop(key, None)
        ctx.state.pop('personal_selected', None)
    ctx.state['personal_storage'] = mode
    if mode == SESSION:
        st.caption('仅在当前会话使用，重启后需要重新上传。首次提问时会准备资料，可能需要稍等。')
    else:
        st.caption('保存后，下次打开仍可使用；保存时会将文字发送到已配置的资料处理服务。')
        st.caption('这是本机学生资料库，不加入教师课程库；当前没有学生账号登录，使用此应用的学生端可访问这个长期资料库。')
    return mode


def selected_store(ctx, mode):
    if mode == SESSION:
        return personal_store(ctx)
    from campus_personal_milvus import PersistentPersonalKnowledge
    return PersistentPersonalKnowledge(persistent_connection(ctx.milvus_settings, ctx.embedding))


def personal_store(ctx):
    if 'personal_documents' not in ctx.state:
        ctx.state['personal_documents'] = PersonalKnowledge()
    return ctx.state['personal_documents']


def personal_files(ctx):
    header('我的资料', '上传自己的课件、笔记或题目，查看原文并围绕文件提问。')
    mode = storage_choice(ctx)
    try:
        store = selected_store(ctx, mode)
        store.documents
    except Exception:
        st.error('长期资料库暂时无法连接，请联系教师检查服务，或切换为“仅本次会话”。未改为其他位置保存。')
        return
    upload = st.file_uploader('上传个人资料', type=['pdf', 'docx', 'txt'], key='personal_upload', max_upload_size=10)
    st.caption('支持 PDF、Word（.docx）、UTF-8 TXT；单文件最大 10 MB、20 万字。扫描文件需先识别成文字。')
    if upload:
        try:
            from ingestion import load_document
            name, _, documents, warnings = load_document(upload)
            body = '\n\n'.join(doc.page_content for doc in documents)
            for warning in warnings:
                st.info(warning)
            with st.expander('上传内容预览', expanded=True):
                st.text_area('提取的文字', body[:6000], height=180, disabled=True)
                st.caption(f'共 {len(body)} 字；预览最多显示 6000 字。')
            if st.button('保存到我的资料', type='primary'):
                with st.spinner('正在处理并长期保存资料…' if mode == PERSISTENT else '正在保存到当前会话…'):
                    ident, added = store.add(name, body)
                ctx.state['personal_selected'] = ident
                st.session_state['personal_file_select'] = ident
                st.success(('已长期保存，下次打开仍可使用。' if mode == PERSISTENT else '已保存，可以查看原文或提问。') if added else '这份内容已存在，已选中原资料。')
        except Exception as error:
            explain_error('读取个人资料', error)
    st.subheader(f'已保存资料 · {len(store.documents)} 份')
    if mode == PERSISTENT:
        if st.button('刷新长期资料列表'):
            st.rerun()
    if not store.documents:
        st.info('还没有个人资料。在上方选择文件，再点击“保存到我的资料”。')
        return
    ids = list(store.documents)
    previous = ctx.state.get('personal_selected')
    if st.session_state.get('personal_file_select') not in ids:
        st.session_state['personal_file_select'] = previous if previous in ids else ids[0]
    selected = st.selectbox('选择个人文件', ids, key='personal_file_select',
                            format_func=lambda ident: store.documents[ident]['name'] + ' · ' + ident[:6])
    ctx.state['personal_selected'] = selected
    try:
        text = store.read(selected)
    except Exception as error:
        explain_error('读取资料原文', error)
        text = None
    if text is not None:
        st.text_area('已保存的原文', text, height=240, disabled=True, key='personal_preview_' + selected)
    def ask_file():
        ctx.state['personal_selected'] = selected
        st.session_state['personal_qa_select'] = selected
        st.session_state['student_qa_source'] = '我的资料'
        go('课程答疑')
    st.button('围绕这份文件提问', on_click=ask_file, type='primary')
    with st.expander('删除这份个人资料'):
        if mode == PERSISTENT:
            st.caption('此操作会从长期资料库删除这份文件，其他会话刷新后也无法再使用它。')
        confirmed = st.checkbox('确认删除文件及其本次问答记录', key='personal_delete_' + selected)
        if st.button('删除个人文件', disabled=not confirmed):
            try:
                store.delete(selected)
                ctx.state.get('personal_qa', {}).pop(selected, None)
                ctx.state.pop('personal_selected', None)
                st.session_state.pop('personal_qa_select', None)
                st.rerun()
            except Exception as error:
                explain_error('删除个人资料', error)


def personal_answer(ctx):
    mode = storage_choice(ctx)
    try:
        store = selected_store(ctx, mode)
        store.documents
    except Exception:
        st.error('长期资料库暂时无法连接，请联系教师检查服务，或切换为“仅本次会话”。')
        return
    if not store.documents:
        st.info('先上传个人课件、笔记或题目，再围绕文件提问。')
        st.button('上传我的资料', on_click=go, args=('我的资料',), type='primary')
        return
    ids = list(store.documents)
    if st.session_state.get('personal_qa_select') not in ids:
        previous = ctx.state.get('personal_selected')
        st.session_state['personal_qa_select'] = previous if previous in ids else ids[0]
    selected = st.selectbox('答疑文件', ids, key='personal_qa_select',
                            format_func=lambda ident: store.documents[ident]['name'] + ' · ' + ident[:6])
    ctx.state['personal_selected'] = selected
    style = st.selectbox('讲解方式', ['分步讲解', '提示引导', '自测练习'], key='personal_style')
    st.caption('提问时，问题和相关文件内容会发送到已配置的 AI 服务；回答仅参考当前选中的文件。')
    qa = ctx.state.setdefault('personal_qa', {}).setdefault(selected, [])
    if st.button('清空这份文件的问答'):
        ctx.state['personal_qa'][selected] = []
        st.rerun()
    for message in qa:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
            sources_panel(message.get('sources', []))
    prompt = st.chat_input('针对这份文件，输入你想理解的问题', key='personal_question')
    if prompt:
        try:
            search = store if mode == PERSISTENT else PersonalSearch(store, ProjectEmbedder(ctx.embedding), ctx.embedding.fingerprint)
            with st.spinner('正在检索你的文件并组织回答…'):
                result = CampusCoordinator(search, ctx.config).ask(prompt, '课程', qa[-6:],
                    document_ids=[selected], response_style=style)
            qa.extend([{'role': 'user', 'content': prompt},
                       {'role': 'assistant', 'content': result['answer'], 'sources': result['sources']}])
            ctx.state['personal_qa'][selected] = qa[-40:]
            st.rerun()
        except Exception as error:
            explain_error('个人资料答疑', error)
