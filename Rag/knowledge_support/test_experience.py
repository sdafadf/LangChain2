"""Regression coverage for observed user-flow failures, without external services."""
import unittest
from unittest.mock import MagicMock, patch
from streamlit.testing.v1 import AppTest
from test_roles import APP, button
from campus_engine import CampusCoordinator, ModelConfig
from campus_practice import demo_pack, pack_id


class ExperienceTests(unittest.TestCase):
    def start(self, role, empty=False):
        code = APP.replace('app.main()', 'kb.list.return_value = []\napp.main()') if empty else APP
        at = AppTest.from_string(code, default_timeout=20).run()
        button(at, '进入' + role).click().run()
        self.assertFalse(at.exception)
        return at

    def test_empty_course_has_working_personal_handoff_and_no_dead_questions(self):
        at = self.start('学生端', empty=True)
        for page in ['学习资料', '课程答疑']:
            at.sidebar.radio[0].set_value(page).run()
            self.assertFalse(at.exception)
            self.assertTrue(any('尚未添加课程资料' in e.value for e in at.info))
            self.assertFalse(at.chat_input)
            self.assertNotIn('for 和 while 循环有什么区别？', [b.label for b in at.button])
            button(at, '上传或查看我的资料').click().run()
            self.assertEqual(at.session_state['workspace_nav'], '我的资料')

    def test_search_can_recover_without_waiting_for_teacher(self):
        at = self.start('学生端')
        at.sidebar.radio[0].set_value('学习资料').run()
        at.text_input(key='course_material_query').set_value('不存在').run()
        self.assertTrue(any('没有找到匹配' in e.value for e in at.info))
        button(at, '清除搜索').click().run()
        self.assertEqual(at.selectbox[0].options, ['循环课程'])

    def test_unanswered_question_cannot_be_saved_as_learning_result(self):
        at = self.start('学生端')
        state = at.session_state['campus_workspace']
        state['qa'] = {'课程': {'signature': 'all|分步讲解', 'messages': [
            {'role': 'user', 'content': '无法回答的问题'},
            {'role': 'assistant', 'content': '没有依据', 'sources': []}]}}
        at.sidebar.radio[0].set_value('课程答疑').run()
        self.assertEqual(len(at.chat_message), 2)
        self.assertNotIn('将这份回答加入本次成果', [b.label for b in at.button])

    def test_published_pack_survives_navigation_and_draft_edits(self):
        at = self.start('教师端')
        at.session_state['campus_workspace']['practice_draft'] = {
            'pack': demo_pack(), 'signature': None, 'editor': 'regression'}
        at.sidebar.radio[0].set_value('备课与练习').run()
        at.radio(key='teacher_prepare').set_value('练习与反馈').run()
        next(c for c in at.checkbox if '已核对题目' in c.label).check().run()
        button(at, '审核通过，启用补练').click().run()
        state = at.session_state['campus_workspace']
        active_id = pack_id(state['practice_active'])
        state['practice_attempts'] = [[0, 1], [2]]
        button(at, '切换身份').click().run()
        button(at, '进入学生端').click().run()
        button(at, '切换身份').click().run()
        button(at, '进入教师端').click().run()
        at.sidebar.radio[0].set_value('备课与练习').run()
        at.radio(key='teacher_prepare').set_value('练习与反馈').run()
        self.assertFalse(at.exception)
        self.assertTrue(next(c for c in at.checkbox if '已核对题目' in c.label).value)
        download = next(d for d in at.get('download_button') if d.label == '下载已启用练习包（含答案）')
        self.assertFalse(download.disabled)
        self.assertTrue(button(at, '审核通过，启用补练').disabled)
        next(t for t in at.text_area if t.label == '首次答错后的提示').set_value('更新后的提示').run()
        self.assertFalse(next(c for c in at.checkbox if '已核对题目' in c.label).value)
        state = at.session_state['campus_workspace']
        self.assertEqual(pack_id(state['practice_active']), active_id)
        self.assertEqual(state['practice_attempts'], [[0, 1], [2]])
        self.assertFalse(next(d for d in at.get('download_button') if d.label == '下载已启用练习包（含答案）').disabled)

    def test_draft_preview_edits_survive_switching_view_and_page(self):
        at = self.start('教师端')
        self.assertEqual(next(r for r in at.radio if r.label == '草稿视图').value, '预览')
        self.assertFalse(any(t.label == '审核与编辑' for t in at.text_area))
        next(r for r in at.radio if r.label == '草稿视图').set_value('编辑').run()
        next(t for t in at.text_area if t.label == '审核与编辑').set_value('## 已编辑标题\n保留这份内容').run()
        next(r for r in at.radio if r.label == '草稿视图').set_value('预览').run()
        self.assertTrue(any('已编辑标题' in m.value for m in at.markdown))
        at.sidebar.radio[0].set_value('学情分析').run()
        at.sidebar.radio[0].set_value('教学首页').run()
        self.assertTrue(any('保留这份内容' in m.value for m in at.markdown))

    def test_teaching_length_reaches_model_and_rejects_invalid_values(self):
        engine = CampusCoordinator(MagicMock(), ModelConfig('本地模型'))
        with patch('campus_engine.generate', return_value='草稿') as generate:
            engine.teaching({'学生数': 4}, '20分钟，一道题', detail='简洁版')
            self.assertIn('600字以内', generate.call_args.args[1])
            self.assertIn('20分钟，一道题', generate.call_args.args[2])
            engine.teaching({'学生数': 4}, '20分钟，一道题', detail='完整版')
            self.assertIn('完整教学目标', generate.call_args.args[1])
            self.assertIn('教师明确指定', generate.call_args.args[1])
        with patch('campus_engine.generate') as generate:
            with self.assertRaises(ValueError):
                engine.teaching({}, '', detail='unknown')
            generate.assert_not_called()


if __name__ == '__main__':
    unittest.main()
