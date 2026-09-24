"""Explicit configuration application and user-triggered connection diagnostics."""
import time
from urllib.parse import urlparse
import streamlit as st
from campus_engine import ModelConfig, generate
from campus_ui import header, explain_error


def settings_page(ctx):
    header('系统设置', '查看服务配置，按需测试连接。修改参数后点击应用，其他页面才会使用新设置。')
    st.subheader('回答生成')
    names = ['原项目 ChatModel','离线工具','本地模型','云端模型']
    mode = st.selectbox('运行模式',names,index=names.index(ctx.config.mode),key='settings_mode')
    with st.form('apply_model_form'):
        base,model,key,consent = ctx.config.base_url,ctx.config.model,ctx.config.api_key,ctx.config.cloud_consent
        if mode=='原项目 ChatModel':
            st.write('模型：'+ctx.project_chat.model)
            st.caption('服务：'+(urlparse(ctx.project_chat.base_url).hostname or '未配置'))
            st.caption('使用原项目 .env 的 ChatModel 配置和密钥。提交生成任务时将发送必要文本至该服务。')
        elif mode=='离线工具':
            st.info('关闭回答生成。学情统计与规则整理可用；知识检索仍调用原 Embedding 服务和 Docker Milvus。')
        else:
            local = mode=='本地模型'
            current = ctx.config.mode==mode
            base = st.text_input('模型接口地址',value=base if current else ('http://127.0.0.1:11434/v1' if local else 'https://api.openai.com/v1'))
            model = st.text_input('模型名称',value=model if current else ('qwen2.5:7b' if local else ''))
            if not local:
                key = st.text_input('API 密钥（仅本次会话）',value=key if current else '',type='password')
                consent = st.checkbox('同意将提交任务的必要文本发送到该服务',value=consent if current else False)
            else:
                key,consent = '',False
        if st.form_submit_button('应用生成设置',type='primary'):
            selected = ctx.project_chat if mode=='原项目 ChatModel' else ModelConfig(mode,base,model,key,consent)
            try:
                selected.validate()
                ctx.state['model_config'] = selected
                ctx.state.pop('qa',None)
                ctx.state.pop('connection_tests',None)
                ctx.state['settings_notice'] = True
                st.rerun()
            except Exception as error:
                explain_error('应用设置',error)
    if ctx.state.pop('settings_notice',False):
        st.success('设置已应用。新任务使用当前配置，对话上下文已清空，已有草稿保留。')
    st.subheader('连接诊断')
    st.caption('仅在点击时测试。模型测试使用合成短句，不读取或发送已有文档。')
    columns = st.columns(3)
    tests = ctx.state.setdefault('connection_tests',{})
    with columns[0].container(border=True):
        st.markdown('### 知识数据库')
        st.write('Docker Milvus')
        st.caption(ctx.milvus_settings.database+'/'+ctx.milvus_settings.collection)
        if st.button('检查知识库连接',width='stretch'):
            try:
                before = time.perf_counter()
                report = ctx.knowledge.status()
                tests['milvus'] = f'连接成功，{report["documents"]} 份资料、{report["chunks"]} 个片段，耗时 {time.perf_counter()-before:.1f} 秒。'
            except Exception:
                tests['milvus'] = '连接失败，请检查 Docker 容器、19530 端口及 MILVUS 配置。'
        if tests.get('milvus'):
            st.caption(tests['milvus'])
    with columns[1].container(border=True):
        st.markdown('### 向量模型')
        st.write(ctx.embedding.model)
        st.caption(urlparse(ctx.embedding.base_url).hostname or '未配置')
        if st.button('测试 Embedding',width='stretch'):
            try:
                result = ctx.knowledge.embedder.embed(['合成连接测试：课程学习'])
                dimension = len(result[0])
                tests['embedding'] = ('连接成功，返回 '+str(dimension)+' 维向量。' if dimension==ctx.milvus_settings.dimension else '返回维度与 Milvus 不一致，请核对配置。')
            except Exception:
                tests['embedding'] = '连接失败，请检查原 OPENAI_BASE_URL、API 密钥与网络。'
        if tests.get('embedding'):
            st.caption(tests['embedding'])
    with columns[2].container(border=True):
        st.markdown('### 回答模型')
        st.write(ctx.config.model if ctx.config.mode!='离线工具' else '当前已关闭')
        st.caption('当前生效：'+ctx.config.mode)
        if st.button('测试 ChatModel',width='stretch',disabled=ctx.config.mode=='离线工具'):
            try:
                result = generate(ctx.config,'只回复连接正常。','合成连接测试，不含用户资料。')
                tests['chat'] = '连接成功，已收到模型响应。' if result else '模型返回空响应。'
            except Exception:
                tests['chat'] = '连接失败，请核对模型、地址、密钥和网络。'
        if tests.get('chat'):
            st.caption(tests['chat'])
    with st.expander('部署、数据与使用说明'):
        st.markdown('''
        - 主界面面向单用户本机试用，岗位入口不是账号权限系统。
        - 上传片段与向量存于 Docker Milvus；不使用 SQLite 作为运行数据库。
        - 问题向量经 Milvus `client.search` 检索资料，再交给原 ChatModel 生成带引用的答案。
        - 当前会话草稿与对话不持久保存；重要成果请在审核后下载。
        - 导出会遮盖常见联系方式和证件号；姓名、学校标识等需人工复核。
        - 生成的教学内容和办公文稿均需审核；系统不会自动审批、发通知或代办事务。
        - 原 Embedding 与 Milvus 连接参数来自项目 `.env`，修改文件后重启服务生效。这里显示服务信息，不展示已有密钥。
        ''')
        st.code('python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8503',language='text')
