"""Task-oriented campus pages built on the existing coordinator and Milvus store."""
import hashlib
import time
import streamlit as st
from campus_core import DEMO_DOCS, DEMO_GRADES, parse_grades, safe_csv
from campus_workspace import make_draft, input_fingerprint, focus_topics, remember_draft, selected_draft
from campus_ui import header, note, go, draft_editor, sources_panel, explain_error


def catalog(ctx, refresh=False):
    state = ctx.state
    cached = state.get('catalog')
    if refresh or not cached or time.time()-cached['time'] > 30:
        try:
            cached = {'rows':ctx.knowledge.list(),'error':False,'time':time.time()}
        except Exception:
            cached = {'rows':[],'error':True,'time':time.time()}
        state['catalog'] = cached
    return cached


def save_result(ctx, title, category, result, signature='', *, task=None):
    draft = make_draft(title, category, result['answer'], signature, result.get('sources'))
    remember_draft(ctx.state, draft, task)
    return draft


def active_draft(ctx, category, *, task=None):
    return selected_draft(ctx.state, category, task)


def home(ctx):
    header('今天，从一项具体任务开始', '围绕教学、学习和办公完成工作。已生成的草稿可在本次会话中继续编辑。')
    cols = st.columns(3)
    tasks = [('教师教学','分析学情，准备下一堂课','导入成绩后识别薄弱项，直接生成教学与练习草稿。',':material/school:'),
             ('学生学习','带着资料，理解一个问题','选择课程资料，按需要获得讲解、提示或自测题。',':material/menu_book:'),
             ('行政办公','整理事务，交付可用文稿','核对办事材料，把会议记录和通知要点变成草稿。',':material/business_center:')]
    for col,(target,title,detail,icon) in zip(cols,tasks):
        with col.container(border=True):
            st.markdown('### '+target)
            st.write(title)
            st.caption(detail)
            st.button('进入'+target,key='home_'+target,on_click=go,args=(target,),icon=icon,width='stretch')
    left,right = st.columns([1.65,1],gap='large')
    with left:
        st.subheader('本次会话成果')
        drafts = ctx.state.get('drafts',[])
        if not drafts:
            with st.container(border=True):
                st.write('还没有生成草稿')
                st.caption('完成一次教学设计或办公整理后，草稿会出现在这里，方便继续修改和下载。')
        else:
            selected = st.selectbox('选择要继续处理的成果',[d['id'] for d in drafts],
                format_func=lambda ident:next(d['created']+' · '+d['category']+' · '+d['title'] for d in drafts if d['id']==ident))
            draft = next(d for d in drafts if d['id']==selected)
            draft_editor(draft)
    with right:
        st.subheader('资料与进度')
        data = catalog(ctx)
        if data['error']:
            st.warning('知识库暂时未连接。学情统计仍可使用，连接诊断请到系统设置。')
        else:
            course = sum(row['分类']=='课程' for row in data['rows'])
            admin = sum(row['分类']=='行政' for row in data['rows'])
            st.metric('可用知识资料',len(data['rows']))
            st.caption(f'课程资料 {course} 份，行政资料 {admin} 份。')
        report = ctx.state.get('grade_result',{}).get('report')
        if report:
            st.success(f'最近学情：{report["学生数"]} 名匿名学生，{report["记录数"]} 条记录。')
            st.caption('可在教师教学中继续生成教学草稿。')
        else:
            st.caption('尚未完成学情分析。可使用合成样例熟悉流程。')
        st.button('管理知识资料',on_click=go,args=('知识中心',),width='stretch',icon=':material/folder_open:')
        st.caption('单用户本机工作台。会话结束后草稿不保留，请及时下载。')


def teaching(ctx, section=None):
    header('学情分析' if section == '学情分析' else '教师教学', '从作业记录找到薄弱知识点，把分析转成下一堂课的行动。')
    tabs = section or st.radio('教学任务',['学情分析','教学设计','补练与反馈'],horizontal=True,key='teaching_section',label_visibility='collapsed')
    if tabs == '补练与反馈':
        from campus_practice_page import teacher_practice
        teacher_practice(ctx)
        return
    if tabs == '教学设计':
        teaching_design(ctx)
        return
    left,right = st.columns([1,1.65],gap='large')
    with left:
        with st.container(border=True):
            st.subheader('准备数据')
            source = st.radio('数据来源',['上传成绩','合成样例'],index=0 if ctx.state.get('grade_source','上传成绩')=='上传成绩' else 1)
            if source != ctx.state.get('grade_source'):
                ctx.state['grade_source'] = source
                ctx.state.pop('grade_result',None)
            if source == '合成样例':
                content = DEMO_GRADES.encode('utf-8')
                st.caption('4 名合成学生，3 个知识点，仅用于演示。')
            else:
                upload = st.file_uploader('上传成绩 CSV',type=['csv'],key='grade_file_'+str(ctx.state.get('upload_epoch',0)))
                if upload:
                    ctx.state['grade_bytes'] = upload.getvalue()
                    ctx.state['grade_name'] = upload.name
                content = ctx.state.get('grade_bytes',b'')
                if content:
                    st.caption('当前文件：'+ctx.state.get('grade_name','成绩文件'))
                    if st.button('清除成绩文件'):
                        ctx.state.pop('grade_bytes',None)
                        ctx.state.pop('grade_result',None)
                        ctx.state['upload_epoch'] = ctx.state.get('upload_epoch',0)+1
                        st.rerun()
            st.download_button('下载 CSV 模板',DEMO_GRADES.encode('utf-8-sig'),'grades-template.csv','text/csv',icon=':material/download:')
            st.caption('字段：学生编号、知识点、得分、满分。不上传姓名等身份字段。')
            with st.expander('分析规则'):
                duplicates = st.checkbox('同一知识点含多次作业，全部保留',value=ctx.state.get('duplicates',False))
                threshold = st.slider('薄弱项关注阈值（%）',0,100,ctx.state.get('threshold',60))
            ctx.state['duplicates'],ctx.state['threshold'] = duplicates,threshold
            fingerprint = input_fingerprint(content,duplicates,threshold)
            if fingerprint != ctx.state.get('grade_fingerprint'):
                ctx.state.pop('grade_result',None)
                ctx.state['grade_fingerprint'] = fingerprint
            if st.button('分析学情',type='primary',width='stretch',disabled=not content,icon=':material/analytics:'):
                try:
                    ctx.state['grade_result'] = ctx.coordinator.analysis(parse_grades(content,duplicates),threshold)
                except Exception as error:
                    explain_error('学情分析',error)
    with right:
        result = ctx.state.get('grade_result')
        st.subheader('学情结果')
        if not result:
            with st.container(border=True):
                st.write('等待一次有效的分析')
                st.caption('在左侧上传成绩或选择合成样例，再点击分析。这里会显示班级概况和薄弱知识点。')
            return
        report = result['report']
        cols = st.columns(3)
        for col,label in zip(cols,['学生数','记录数','总得分率%']):
            col.metric(label,report[label])
        st.caption('得分率按得分之和 / 满分之和计算，不代表个体掌握概率。')
        import pandas as pd
        st.bar_chart(pd.DataFrame(report['知识点']).set_index('知识点')['得分率%'],horizontal=True,color='#197b70',height=200)
        st.dataframe(report['知识点'],hide_index=True,width='stretch')
        note('建议关注：'+focus_topics(report))
        def open_design():
            st.session_state['workspace_nav'] = '备课与练习'
            st.session_state['teacher_prepare'] = '教学设计'
        st.button('带入学情，继续教学设计',type='primary',on_click=open_design,icon=':material/edit_note:')
        with st.expander('导出学情汇总'):
            confirmed = st.checkbox('已核对汇总内容，不含个人身份和学校信息')
            st.download_button('下载学情汇总',safe_csv(report['知识点'],['知识点','记录数','得分率%','需关注']),
                               'learning-summary.csv','text/csv',disabled=not confirmed)


def teaching_design(ctx):
    result = ctx.state.get('grade_result')
    if not result:
        st.info('先完成学情分析，教学设计会自动携带统计结果和薄弱知识点。')
        st.button('返回学情分析',on_click=go,args=('学情分析',))
        return
    report = result['report']
    note(f'已带入 {report["学生数"]} 名匿名学生的汇总数据。关注知识点：'+focus_topics(report))
    left,right = st.columns([1,1.7],gap='large')
    with left.container(border=True):
        st.subheader('明确教学目标')
        kind = st.selectbox('希望得到什么',['补弱教学方案','课堂互动与练习','课程内容改进'])
        objective = st.text_area('课程背景与具体要求',value=ctx.state.get('teaching_objective',''),placeholder='例如：Python 入门，45 分钟课堂，帮助学生理解函数返回值。',height=170,max_chars=2000)
        ctx.state['teaching_objective'] = objective
        detail = st.radio('草稿详略', ['简洁版', '完整版'], horizontal=True,
                          index=0 if ctx.state.get('teaching_detail', '简洁版') == '简洁版' else 1)
        ctx.state['teaching_detail'] = detail
        st.caption('简洁版：目标、课堂步骤和一题检测；完整版：展开活动、练习和改进建议。具体要求以你填写的内容为准。')
        if st.button('生成教学草稿',type='primary',width='stretch',disabled=ctx.config.mode=='离线工具'):
            try:
                with st.spinner('正在结合汇总学情生成教学草稿…'):
                    generated = ctx.coordinator.teaching(report,'输出类型：'+kind+'\n'+objective, detail=detail)
                save_result(ctx,kind,'教学',generated,ctx.state['grade_fingerprint'])
            except Exception as error:
                explain_error('教学设计',error)
        if ctx.config.mode == '离线工具':
            st.caption('当前关闭回答生成。可到系统设置启用原 ChatModel。')
        if st.button('采用本地规则建议',width='stretch'):
            save_result(ctx,'教学行动建议','教学',result,ctx.state['grade_fingerprint'])
    with right:
        st.subheader('审核教学草稿')
        draft = active_draft(ctx,'教学')
        if draft:
            if draft['source_signature'] != ctx.state['grade_fingerprint']:
                st.warning('这份草稿来自之前的学情数据；请重新生成或核对后使用。')
            draft_editor(draft)
        else:
            st.caption('生成后可在这里修改。练习题、参考答案和教学安排均需教师审核。')
            with st.expander('查看本地规则建议'):
                st.markdown(result['answer'])


def answer_workspace(ctx, category):
    data = catalog(ctx)
    rows = [r for r in data['rows'] if r['分类']==category]
    if data['error']:
        st.warning('暂时无法读取资料列表。请联系教师检查资料服务。')
    elif not rows:
        st.info('教师尚未添加课程资料。你可以先上传自己的课件或笔记，再围绕文件提问。' if category == '课程'
                else '尚未添加办事资料。请先在教学资料中上传相关制度，再进行有依据的咨询。')
    if data['error'] or not rows:
        if category == '课程':
            st.button('上传或查看我的资料', on_click=go, args=('我的资料',), type='primary', key='qa_personal')
            st.button('查看我的练习', on_click=go, args=('我的练习',), key='qa_practice')
        else:
            st.button('前往教学资料', on_click=go, args=('教学资料',), type='primary')
        if st.button('刷新资料列表', key='qa_refresh_' + category):
            catalog(ctx, True)
            st.rerun()
        return
    settings, style_col = st.columns([1.3,1])
    preferences = ctx.state.setdefault('qa_preferences',{}).setdefault(category,{})
    with settings:
        ids = ['all'] + [r['id'] for r in rows]
        previous_scope = preferences.get('scope','all')
        selected = st.selectbox('资料范围',ids,index=ids.index(previous_scope) if previous_scope in ids else 0,
                               format_func=lambda ident:'全部'+category+'资料' if ident=='all' else next(r['来源'] for r in rows if r['id']==ident),key='qa_scope_'+category)
    with style_col:
        styles = ['分步讲解','提示引导','自测练习']
        style = (st.selectbox('学习方式',styles,index=styles.index(preferences.get('style','分步讲解')),key='qa_style')
                 if category=='课程' else '办理步骤与材料')
        if category=='行政':
            st.caption('回答包含：办理步骤、材料清单与待确认事项。')
    preferences.update(scope=selected,style=style)
    signature = selected+'|'+style
    qa = ctx.state.setdefault('qa',{}).setdefault(category,{'signature':signature,'messages':[]})
    if qa['signature'] != signature:
        qa.update(signature=signature,messages=[])
    history = qa['messages']
    if st.button('新建对话',key='new_chat_'+category,icon=':material/add_comment:'):
        qa['messages'] = []
        st.rerun()
    prompt = None
    if not history:
        st.subheader('从一个问题开始')
        examples = ['for 和 while 循环有什么区别？','函数参数和返回值怎么理解？'] if category=='课程' else ['设备借用需要准备哪些材料？','教室使用申请有哪些步骤？']
        cols = st.columns(2)
        for col,example in zip(cols,examples):
            if col.button(example,key='ask_'+category+example,width='stretch'):
                prompt = example
        st.caption('问题先匹配所选资料，再由模型生成回答。没有依据时会明确提示。')
    for message in history:
        with st.chat_message(message['role']):
            st.markdown(message['content'])
            if message['role']=='assistant':
                sources_panel(message.get('sources',[]))
    typed = st.chat_input('输入课程问题，或继续补充你的理解' if category=='课程' else '输入具体办事事项与已有条件',key='input_'+category)
    prompt = typed or prompt
    if prompt:
        try:
            with st.spinner('正在检索资料并组织回答…'):
                response = ctx.coordinator.ask(prompt,category,history[-6:],
                    document_ids=None if selected=='all' else [selected],response_style=style)
            history.extend([{'role':'user','content':prompt},{'role':'assistant','content':response['answer'],'sources':response['sources']}])
            qa['messages'] = history[-40:]
            st.rerun()
        except Exception as error:
            explain_error('资料答疑',error)
    if history and history[-1].get('role') == 'assistant' and history[-1].get('sources'):
        last = history[-1]
        if st.button('将这份回答加入本次成果',key='keep_'+category,icon=':material/bookmark_add:'):
            save_result(ctx,'答疑摘录','学习' if category=='课程' else '办公',{'answer':last['content'],'sources':last.get('sources',[])})
            st.success('已加入工作台的本次会话成果，可在那里编辑和导出。')


def learning(ctx):
    header('学生学习', '先选择资料和学习方式，再提出问题。让答案有依据，也让思路看得见。')
    task = st.radio('学习任务', ['资料答疑', '专项补练'], horizontal=True, key='learning_task')
    if task == '专项补练':
        from campus_practice_page import student_practice
        student_practice(ctx)
        return
    answer_workspace(ctx,'课程')


def office(ctx):
    header('办公工具', '先明确事务，再整理内容。把可核对的草稿交到下一步。')
    task = st.radio('办公任务',['办事咨询','会议纪要与待办','通知草稿'],horizontal=True,label_visibility='collapsed')
    if task=='办事咨询':
        answer_workspace(ctx,'行政')
        return
    left,right = st.columns([1,1.55],gap='large')
    with left.container(border=True):
        st.subheader('提供原始内容')
        key = 'office_input_'+task
        def fill_demo():
            st.session_state[key] = ('会议讨论下周开展教学研讨。资料管理员负责周五前整理课程案例。教研负责人确认教室安排。会议时间待确认。'
                                    if task=='会议纪要与待办' else '拟组织教学经验交流，请参加人员准备一个课堂互动案例，时间地点待确认。')
        st.button('填入合成示例',on_click=fill_demo,icon=':material/description:')
        text = st.text_area('会议记录或通知要点',value=ctx.state.setdefault('office_inputs',{}).get(task,''),height=260,max_chars=20000,key=key,
                            placeholder='粘贴原文。已知的时间、对象和负责人尽量写清；未知的信息会标为待确认。')
        ctx.state['office_inputs'][task] = text
        if st.button('生成办公草稿',type='primary',width='stretch',disabled=not text.strip()):
            try:
                with st.spinner('正在整理原文…'):
                    result = ctx.coordinator.office(task,text)
                save_result(ctx,task,'办公',result,hashlib.sha256(text.encode()).hexdigest(),task=task)
            except Exception as error:
                explain_error('办公整理',error)
        st.caption('生成只产生草稿，不自动发布、审批或发送通知。')
    with right:
        st.subheader('审核与交付')
        draft = active_draft(ctx,'办公',task=task)
        if draft:
            draft_editor(draft)
        else:
            with st.container(border=True):
                st.write('草稿将在这里呈现')
                st.caption('你可以修改措辞、确认负责人和日期，再预览并下载。')


def knowledge_center(ctx):
    header('教学资料', '课程与制度分类管理。上传的资料决定回答依据，变更前请核对内容。')
    data = catalog(ctx)
    if data['error']:
        st.error('知识库暂时不可用，请到系统设置检查 Docker Milvus。')
        if st.button('重新读取知识库'):
            catalog(ctx,True)
            st.rerun()
        return
    rows = data['rows']
    cols = st.columns(3)
    cols[0].metric('已完成资料',len(rows))
    cols[1].metric('课程资料',sum(r['分类']=='课程' for r in rows))
    cols[2].metric('行政资料',sum(r['分类']=='行政' for r in rows))
    task = st.radio('资料任务',['资料目录','上传资料'],horizontal=True,label_visibility='collapsed')
    if task=='上传资料':
        left,right = st.columns([1,1.5],gap='large')
        with left.container(border=True):
            category = st.selectbox('资料用途',['课程','行政'])
            upload = st.file_uploader('选择知识文档',type=['txt','pdf','docx'])
            st.caption('支持 UTF-8 文本、可提取文字的 PDF 和 Word，最大 10 MB。扫描文件先做文字识别。')
        with right:
            st.subheader('先核对，再入库')
            if not upload:
                st.caption('选择文件后显示原文预览。只有点击入库按钮才调用原 Embedding 服务。')
            else:
                try:
                    from ingestion import load_document
                    name,digest,documents,warnings = load_document(upload)
                    body = '\n\n'.join(doc.page_content for doc in documents)
                    for warning in warnings:
                        st.warning(warning)
                    st.text_area('原文预览',body[:6000],height=260,disabled=True)
                    st.caption(f'{len(body)} 字；当前用途：{category}。预览最多显示 6000 字。')
                    if st.button('确认内容，生成向量并入库',type='primary'):
                        with st.spinner('正在生成向量并写入 Milvus…'):
                            added = ctx.knowledge.add(name,category,body)
                        catalog(ctx,True)
                        st.success('资料已入库，可在答疑页选择。' if added else '已有相同内容，已跳过重复导入。')
                except Exception as error:
                    explain_error('文档入库',error)
        return
    filters = st.columns([1,2,1])
    category = filters[0].selectbox('分类',['全部','课程','行政'])
    query = filters[1].text_input('搜索资料名称',placeholder='输入关键词')
    if filters[2].button('刷新列表',icon=':material/refresh:',width='stretch'):
        catalog(ctx,True)
        st.rerun()
    shown = [r for r in rows if (category=='全部' or r['分类']==category) and query.casefold() in r['来源'].casefold()]
    if shown:
        st.dataframe([{k:v for k,v in r.items() if k!='id'} for r in shown],hide_index=True,width='stretch')
    else:
        st.info('没有匹配资料。可调整筛选条件，或到上传资料添加文件。')
    with st.expander('演示资料与删除操作'):
        if st.button('添加合成演示资料'):
            try:
                with st.spinner('正在准备演示知识…'):
                    count = sum(ctx.knowledge.add(*doc) for doc in DEMO_DOCS)
                catalog(ctx,True)
                st.success(f'已添加 {count} 份合成资料，相同内容已跳过。')
            except Exception as error:
                explain_error('添加示例',error)
        if shown:
            selected = st.selectbox('要删除的资料',[r['id'] for r in shown],format_func=lambda ident:next(r['来源'] for r in shown if r['id']==ident))
            confirm = st.checkbox('已确认删除对象及影响',key='delete_confirm_'+selected)
            if st.button('删除选中资料',disabled=not confirm):
                try:
                    ctx.knowledge.delete(selected)
                    ctx.state.pop('qa',None)
                    catalog(ctx,True)
                    st.rerun()
                except Exception as error:
                    explain_error('删除资料',error)
