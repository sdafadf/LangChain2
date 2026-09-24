import unittest
from unittest.mock import patch

from campus_navigation import Page, PageRegistry, PAGES
from campus_workspace import make_draft, remember_draft, selected_draft


class CompositionTests(unittest.TestCase):
    def test_office_ui_switch_keeps_each_tasks_output(self):
        from streamlit.testing.v1 import AppTest
        from test_roles import APP, button
        at = AppTest.from_string(APP, default_timeout=20).run()
        button(at, '进入教师端').click().run()
        at.sidebar.radio[0].set_value('办公工具').run()
        task_radio = lambda: next(r for r in at.radio if r.label == '办公任务')
        task_radio().set_value('会议纪要与待办').run()
        button(at, '填入合成示例').click().run()
        button(at, '生成办公草稿').click().run()
        self.assertFalse(at.exception)
        state = at.session_state['campus_workspace']
        meeting = selected_draft(state, '办公', '会议纪要与待办')
        self.assertIsNotNone(meeting)
        task_radio().set_value('通知草稿').run()
        self.assertFalse(at.exception)
        self.assertTrue(any(item.value == '草稿将在这里呈现' for item in at.markdown))
        button(at, '填入合成示例').click().run()
        button(at, '生成办公草稿').click().run()
        task_radio().set_value('会议纪要与待办').run()
        self.assertFalse(at.exception)
        self.assertEqual(selected_draft(at.session_state['campus_workspace'], '办公', '会议纪要与待办')['id'], meeting['id'])

    def test_task_results_are_independent_and_survive_switching(self):
        state = {}
        meeting = make_draft('会议纪要与待办', '办公', 'meeting')
        notice = make_draft('通知草稿', '办公', 'notice')
        remember_draft(state, meeting, '会议纪要与待办')
        self.assertIsNone(selected_draft(state, '办公', '通知草稿'))
        remember_draft(state, notice, '通知草稿')
        self.assertIs(selected_draft(state, '办公', '会议纪要与待办'), meeting)
        self.assertIs(selected_draft(state, '办公', '通知草稿'), notice)
        self.assertIsNone(selected_draft({}, '办公', '通知草稿'))

    def test_existing_drafts_do_not_leak_between_tasks(self):
        meeting = make_draft('会议纪要与待办', '办公', 'old meeting')
        state = {'drafts': [meeting], 'active_办公': meeting['id']}
        self.assertIs(selected_draft(state, '办公', '会议纪要与待办'), meeting)
        self.assertIsNone(selected_draft(state, '办公', '通知草稿'))
        self.assertIs(selected_draft(state, '办公'), meeting)

    def test_registration_controls_navigation_dispatch_and_role_access(self):
        page = Page('新任务', ('教师端',), 'campus_pages', 'teaching', {'section': 'test'})
        registry = PageRegistry([page])
        self.assertEqual(registry.navigation('教师端'), ['新任务'])
        self.assertEqual(registry.navigation('学生端'), [])
        self.assertIsNone(registry.resolve('学生端', '新任务'))
        context = object()
        with patch('campus_pages.teaching') as handler:
            registry.resolve('教师端', '新任务').render(context)
            handler.assert_called_once_with(context, section='test')
        with self.assertRaises(ValueError):
            PageRegistry([page, page])
        self.assertIsNone(PAGES.resolve('学生端', '系统设置'))
        self.assertNotIn('系统设置', PAGES.navigation('教师端'))


if __name__ == '__main__':
    unittest.main()
