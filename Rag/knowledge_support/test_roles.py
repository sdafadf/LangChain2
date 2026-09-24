import unittest
from streamlit.testing.v1 import AppTest

APP = '''
import os
os.environ['CAMPUS_CHAT_MODE'] = 'offline'
import campus_app as app
from types import SimpleNamespace
from unittest.mock import MagicMock
from campus_engine import ModelConfig
from campus_practice import demo_pack, pack_id
from campus_workspace import make_draft
import streamlit as st
kb = MagicMock()
kb.list.return_value = [
    {'id':'course1','分类':'课程','来源':'循环课程'},
    {'id':'admin1','分类':'行政','来源':'内部办公资料'},
]
app.get_knowledge = lambda settings, embedding: kb
app.EmbeddingConfig.from_project = lambda root: SimpleNamespace(model='test', base_url='http://localhost')
app.MilvusSettings.from_project = lambda root: SimpleNamespace(database='test', collection='test', dimension=3)
app.ModelConfig.from_project = lambda root: ModelConfig()
if 'campus_workspace' not in st.session_state:
    st.session_state['campus_workspace'] = {'drafts':[
        make_draft('教师私有草稿','教学','教师内容'),
        make_draft('学生学习摘录','学习','学习内容'),
    ]}
app.main()
'''


def button(at, label):
    return next(b for b in at.button if b.label == label)


class RoleFlowTests(unittest.TestCase):
    def start(self, role):
        at = AppTest.from_string(APP, default_timeout=20).run()
        self.assertFalse(at.exception)
        button(at, '进入' + role).click().run()
        self.assertFalse(at.exception)
        return at

    def test_role_switch_and_drafts(self):
        at = self.start('教师端')
        self.assertEqual(at.selectbox[0].options, ['教师私有草稿'])
        button(at, '切换身份').click().run()
        button(at, '进入学生端').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox[0].options, ['学生学习摘录'])
        self.assertEqual(at.sidebar.radio[0].options, ['学习首页','课程答疑','我的练习','学习资料','我的资料','智能任务','我的技能'])
        self.assertNotIn('系统设置', [b.label for b in at.button])
        stale_app = APP.replace('app.main()', "st.session_state['campus_role'] = '学生端'\nst.session_state['workspace_nav'] = '系统设置'\napp.main()")
        at = AppTest.from_string(stale_app, default_timeout=20).run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['workspace_nav'], '学习首页')

    def test_student_materials_readonly_and_handoff(self):
        at = self.start('学生端')
        at.sidebar.radio[0].set_value('学习资料').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox[0].options, ['循环课程'])
        self.assertEqual(len(at.get('file_uploader')), 0)
        button(at, '围绕这份资料提问').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['workspace_nav'], '课程答疑')
        self.assertEqual(at.selectbox(key='qa_scope_课程').value, 'course1')

    def test_publish_answer_feedback(self):
        from campus_practice import demo_pack
        at = self.start('教师端')
        state = at.session_state['campus_workspace']
        state['practice_draft'] = {'pack':demo_pack(), 'signature':None, 'editor':'test'}
        at.sidebar.radio[0].set_value('备课与练习').run()
        at.radio(key='teacher_prepare').set_value('练习与反馈').run()
        self.assertFalse(at.exception)
        next(c for c in at.checkbox if '已核对题目' in c.label).check().run()
        button(at, '审核通过，启用补练').click().run()
        self.assertFalse(at.exception)
        self.assertIn('practice_active', at.session_state['campus_workspace'])
        button(at, '切换身份').click().run()
        button(at, '进入学生端').click().run()
        at.sidebar.radio[0].set_value('我的练习').run()
        self.assertFalse(at.exception)
        pack = at.session_state['campus_workspace']['practice_active']
        next(r for r in at.radio if r.label == '选择答案').set_value(pack['questions'][0]['answer']).run()
        button(at, '提交本题答案').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.session_state['campus_workspace']['practice_attempts'][0], [pack['questions'][0]['answer']])
        button(at, '切换身份').click().run()
        button(at, '进入教师端').click().run()
        at.sidebar.radio[0].set_value('备课与练习').run()
        at.radio(key='teacher_prepare').set_value('练习与反馈').run()
        self.assertFalse(at.exception)
        self.assertTrue(any(s.value == '复核作答反馈' for s in at.subheader))

    def test_imported_practice_does_not_overwrite_published_feedback(self):
        from campus_practice import demo_pack
        at = self.start('学生端')
        state = at.session_state['campus_workspace']
        state['practice_active'] = demo_pack()
        state['practice_attempts'] = [[], []]
        imported = demo_pack()
        imported['topic'] = '接收的练习'
        state['student_import_pack'] = imported
        at.sidebar.radio[0].set_value('我的练习').run()
        at.radio(key='student_pack_source').set_value('导入的练习').run()
        next(r for r in at.radio if r.label == '选择答案').set_value(imported['questions'][0]['answer']).run()
        button(at, '提交本题答案').click().run()
        self.assertFalse(at.exception)
        state = at.session_state['campus_workspace']
        self.assertEqual(state['practice_attempts'], [[], []])
        self.assertTrue(state['student_import_attempts'][0])

    def test_teacher_navigation_and_settings(self):
        at = self.start('教师端')
        for page in ['学情分析', '备课与练习', '教学资料', '办公工具', '教学首页']:
            at.sidebar.radio[0].set_value(page).run()
            self.assertFalse(at.exception, page)
        button(at, '系统设置').click().run()
        self.assertFalse(at.exception)
        button(at, '返回教学首页').click().run()
        self.assertFalse(at.exception)


if __name__ == '__main__':
    unittest.main()
