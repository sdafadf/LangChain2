import hashlib

import streamlit as st

from backend import safe_error
from ingestion import prepare_document, save_to_milvus


def render_upload(kb):
    st.title('上传知识文档')
    st.caption('选择文件 → 预览切分 → 导入知识库。上传完成后即可返回客服对话提问。')
    st.info('支持 UTF-8 TXT、文字版 PDF、Word（.docx），单文件最多 10 MB。内容相同的文件会跳过；同名但内容不同的文件会作为新文档追加。')
    uploaded = st.file_uploader('选择知识文档', type=['txt', 'pdf', 'docx'], key='knowledge_upload')
    if uploaded is None:
        st.session_state.pop('upload_preview', None)
        return
    signature = (uploaded.name, hashlib.sha256(uploaded.getvalue()).hexdigest())
    current = st.session_state.get('upload_preview')
    if current is None or current[0] != signature:
        st.session_state.pop('upload_preview', None)
        try:
            with st.spinner('正在本地解析和切分…'):
                prepared = prepare_document(uploaded)
            st.session_state.upload_preview = (signature, prepared)
        except Exception as error:
            st.error('文档解析失败，请检查文件格式和内容。')
            st.code(safe_error(error), language=None)
            return
    prepared = st.session_state.upload_preview[1]
    left, right = st.columns(2)
    left.metric('知识片段', len(prepared.chunks))
    right.metric('文本字符数（含重叠部分）', sum(len(c.page_content) for c in prepared.chunks))
    for warning in prepared.warnings[:5]:
        st.warning(warning)
    if len(prepared.warnings) > 5:
        st.caption(f'另有 {len(prepared.warnings) - 5} 条空白页提示。')
    with st.expander('预览切分结果', expanded=True):
        for i, chunk in enumerate(prepared.chunks[:5], 1):
            st.markdown(f'**片段 {i}**')
            if chunk.metadata.get('page'):
                st.caption(f'第 {chunk.metadata["page"]} 页')
            st.text(chunk.page_content)
        if len(prepared.chunks) > 5:
            st.caption(f'显示前 5 个片段，共 {len(prepared.chunks)} 个。')
    st.caption(f'目标知识库：{kb.settings.database} / {kb.settings.collection}')
    st.caption('点击导入会将文档文字发送到当前配置的向量模型服务，并把向量和原文保存到 Milvus。')
    if st.button('导入知识库', type='primary', key='import_document'):
        bar = st.progress(0.0, text='准备导入…')
        try:
            result = save_to_milvus(prepared, kb, lambda value, text: bar.progress(value, text=text))
            st.session_state.kb_status = None
            if result['status'] == 'duplicate':
                st.info('此文件已经完整导入，本次未重复写入，也未再次生成向量。')
            else:
                st.success(f'导入完成！新增 {result["written"]} 个片段，文档共 {result["total"]} 个片段。可切换到“客服对话”提问。')
        except Exception as error:
            bar.empty()
            st.error('导入未完成。已写入的部分会保留；解决错误后再次点击导入，将补齐缺失片段。')
            with st.expander('查看导入错误详情', expanded=True):
                st.code(safe_error(error), language=None)
