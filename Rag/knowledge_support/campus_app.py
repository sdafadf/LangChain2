"""Campus workspace shell: navigation and connection ownership only."""
import os
from dataclasses import dataclass
from pathlib import Path

os.environ['LANGSMITH_TRACING'] = 'false'
os.environ['LANGCHAIN_TRACING_V2'] = 'false'
import streamlit as st
from campus_embeddings import EmbeddingConfig
from campus_engine import ModelConfig, CampusCoordinator
from campus_milvus import MilvusKnowledge, MilvusSettings
from campus_ui import theme
from campus_roles import ROLE_NAV, select_role, change_role, render_page
from campus_navigation import PAGES
from campus_pages import home, teaching, learning, office, knowledge_center
from campus_settings_page import settings_page


@dataclass
class Context:
    state: dict
    embedding: EmbeddingConfig
    project_chat: ModelConfig
    milvus_settings: MilvusSettings
    config: ModelConfig
    knowledge: object
    coordinator: CampusCoordinator


@st.cache_resource
def get_knowledge(settings, embedding):
    return MilvusKnowledge(settings,embedding)


def main():
    st.set_option('client.toolbarMode', 'viewer')
    st.set_page_config(page_title='校园智助 · 教师与学生工作区',page_icon=':material/school:',layout='wide')
    theme()
    role = st.session_state.get('campus_role')
    if role not in ROLE_NAV:
        select_role()
        return
    root = Path(os.getenv('CAMPUS_CONFIG_ROOT',str(Path(__file__).resolve().parent)))
    try:
        embedding = EmbeddingConfig.from_project(root)
        project_chat = ModelConfig.from_project(root)
        milvus_settings = MilvusSettings.from_project(root)
    except Exception:
        st.error('配置读取失败，请检查项目 .env 中模型与 Milvus 参数的格式。')
        return
    state = st.session_state.setdefault('campus_workspace',{})
    config = state.setdefault('model_config',ModelConfig() if os.getenv('CAMPUS_CHAT_MODE')=='offline' else project_chat)
    knowledge = get_knowledge(milvus_settings,embedding)
    ctx = Context(state,embedding,project_chat,milvus_settings,config,knowledge,CampusCoordinator(knowledge,config))
    with st.sidebar:
        st.title('校园智助')
        st.caption(role + ' · 专注当前任务')
        st.button('切换身份', on_click=change_role)
        st.divider()
        navigation = ROLE_NAV[role]
        if PAGES.resolve(role, st.session_state.get('workspace_nav')) is None:
            st.session_state['workspace_nav'] = navigation[0]
        # 设置是独立入口，不挤占日常任务导航。
        if st.session_state['workspace_nav'] != '系统设置':
            st.session_state['workspace_nav_choice'] = st.session_state['workspace_nav']
            st.radio('工作空间', navigation, key='workspace_nav_choice', label_visibility='collapsed',
                     on_change=lambda: st.session_state.update(workspace_nav=st.session_state['workspace_nav_choice']))
        else:
            st.button('返回教学首页', on_click=lambda: st.session_state.update(workspace_nav='教学首页'))
        if role == '教师端':
            with st.expander('管理入口'):
                st.button('系统设置', on_click=lambda: st.session_state.update(workspace_nav='系统设置'))
        st.divider()
        st.caption('本机角色分区 · 不代表账号登录')
        st.caption('记录保留在本次会话，请及时下载。')
    render_page(ctx, role, st.session_state['workspace_nav'])



if __name__ == '__main__':
    main()
