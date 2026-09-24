"""Visual tokens and shared interactions. No database or model calls."""
import hashlib
from html import escape
import streamlit as st
from campus_core import redact

NAV = ['工作台', '教师教学', '学生学习', '行政办公', '知识中心', '系统设置']


def theme():
    st.markdown('''<style>
    :root{--brand:#197b70;--ink:#20334d;--muted:#526278;--line:#e2e8ef}
    html,body,[data-testid="stApp"]{font-family:"Microsoft YaHei","PingFang SC",sans-serif;color:var(--ink)}
    .stApp{background:#f5f7fa}.block-container{max-width:1240px;padding:2rem 2.6rem 3rem}
    [data-testid="stSidebar"]{background:#fff;border-right:1px solid var(--line);min-width:240px!important;max-width:260px!important}
    [data-testid="stSidebar"] h1{font-size:23px;letter-spacing:-.5px;color:var(--ink)}
    [data-testid="stSidebar"] [data-testid="stRadio"] label{padding:8px 4px;font-size:15px}
    [data-testid="stCaptionContainer"],[data-testid="stCaptionContainer"] p{color:var(--muted)!important}
    [data-testid="stCaptionContainer"]{opacity:1!important}
    [data-testid="stCaption"],[data-testid="stCaption"] p{color:var(--muted)!important}
    input::placeholder,textarea::placeholder{color:#596a80!important;opacity:1!important}
    textarea:disabled{color:#526278!important;-webkit-text-fill-color:#526278!important;opacity:1!important}
    .pagehead{padding-bottom:18px;border-bottom:1px solid var(--line);margin-bottom:24px}
    .pagehead h1{font-size:29px;line-height:1.4;margin:0 0 8px;font-weight:700;letter-spacing:-.5px}
    .pagehead p{font-size:14px;color:var(--muted);margin:0;line-height:1.8;max-width:760px}
    h2{font-size:21px!important}h3{font-size:18px!important}
    [data-testid="stVerticalBlockBorderWrapper"]>div{border-radius:12px!important}
    [data-testid="stMetric"]{background:#fff;border:1px solid var(--line);border-radius:10px;padding:14px 18px}
    [data-testid="stMetricValue"]{font-size:27px}
    [data-testid="stChatMessage"]{background:white;border:1px solid var(--line);border-radius:12px;padding:18px}
    .stButton button,.stDownloadButton button{border-radius:8px;min-height:40px}
    .stButton button[kind="primary"]{background:var(--brand);border-color:var(--brand)}
    .stButton button:focus-visible,.stDownloadButton button:focus-visible{outline:3px solid #85c7bd;outline-offset:2px}
    .workflow-note{border-left:3px solid var(--brand);padding:10px 14px;background:#edf6f3;color:#315d56;font-size:14px;line-height:1.8;margin-bottom:16px}
    [data-testid="stHeader"]{background:transparent}
    [data-testid="stAppDeployButton"]{display:none}
    [data-testid="stSkillsNudge"]{display:none}
    @media(max-width:760px){.block-container{padding:1.5rem 1rem 2rem}.pagehead h1{font-size:25px}.pagehead{margin-bottom:16px}}
    @media(prefers-reduced-motion:reduce){*{scroll-behavior:auto!important;animation:none!important;transition:none!important}}
    </style>''', unsafe_allow_html=True)


def header(title, text):
    st.markdown(f'<div class="pagehead"><h1>{escape(title)}</h1><p>{escape(text)}</p></div>',unsafe_allow_html=True)


def note(text):
    st.markdown(f'<div class="workflow-note">{escape(text)}</div>',unsafe_allow_html=True)


def go(page):
    st.session_state['workspace_nav'] = page


def explain_error(operation, error):
    if isinstance(error, ValueError):
        st.error(str(error))
    else:
        st.error(operation+'未完成。请检查输入和服务连接后重试；教师可在管理入口检查连接。')


def sources_panel(sources):
    if sources:
        with st.expander(f'参考资料 · {len(sources)} 个片段'):
            for source in sources:
                st.markdown('**['+source['reference']+']**')
                st.text(source['source'])
                st.text(source['text'])
            st.caption('相似度仅用于检索排序；请结合原文核对答案。')


def draft_editor(draft):
    st.caption('先阅读草稿，需要调整时切换到“编辑”。成果只保留在本次会话，重要内容请及时下载。')
    key = 'draft_edit_'+draft['id']
    mode = st.radio('草稿视图', ['预览', '编辑'], horizontal=True, key=key+'_view')
    if mode == '编辑':
        edited = st.text_area('审核与编辑', value=draft['content'], height=450, key=key)
        draft['content'] = edited
    else:
        edited = draft['content']
        with st.container(border=True):
            st.markdown(edited)
    sources_panel(draft.get('sources',[]))
    with st.expander('导出预览与脱敏', expanded=False):
        digest = hashlib.sha256(edited.encode()).hexdigest()[:12]
        export_key = 'draft_export_'+draft['id']+digest
        output = st.text_area('导出文本', value=redact(edited), height=190, key=export_key)
        st.caption('自动遮盖常见手机号、邮箱与证件号；姓名和学校标识请人工复核。')
        confirmed = st.checkbox('已核对个人信息与学校标识', key=export_key+'_confirm')
        st.download_button('下载审核稿', output.encode('utf-8'), 'campus-draft.md','text/markdown',
                           disabled=not confirmed,key=export_key+'_download',icon=':material/download:')
