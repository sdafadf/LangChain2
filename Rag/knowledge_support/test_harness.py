import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import httpx
from langchain_deepseek import ChatDeepSeek
from campus_engine import ModelConfig
from campus_skills import SkillLibrary, Skill, parse_skill, skill_text
from campus_harness import RunContext, build_tools, run_task


def tool_call(name, arguments, ident):
    return {'id': ident, 'type': 'function', 'function': {'name': name, 'arguments': json.dumps(arguments)}}


class FakeEndpoint:
    """Real ChatDeepSeek serialization and DeepAgents graph, deterministic HTTP."""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.client = httpx.Client(transport=httpx.MockTransport(self.handle))
        self.model = ChatDeepSeek(model='deepseek-test-campus', api_key='synthetic-test-key', http_client=self.client, max_retries=0)

    def handle(self, request):
        self.requests.append(json.loads(request.content))
        content, calls = next(self.replies)
        message = {'role': 'assistant', 'content': content}
        if calls:
            message['tool_calls'] = calls
        return httpx.Response(200, json={'id': f'test-{len(self.requests)}', 'object': 'chat.completion',
            'created': 1, 'model': 'deepseek-test-campus', 'choices': [{'index': 0, 'message': message,
            'finish_reason': 'tool_calls' if calls else 'stop'}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 10, 'total_tokens': 20}})


class SkillTests(unittest.TestCase):
    def test_save_reload_disable_and_role_partition(self):
        with tempfile.TemporaryDirectory() as root:
            library = SkillLibrary(root, '教师端')
            library.save('my-review', '复习时使用', '步骤一', reference='参考内容')
            self.assertEqual(library.snapshot()[0].reference, '参考内容')
            self.assertEqual(SkillLibrary(root, '学生端').snapshot(), [])
            library.save('my-review', '复习时使用', '新的步骤', enabled=False)
            self.assertEqual(library.snapshot(), [])
            self.assertEqual(library.list()[0][0].body, '新的步骤')
            with self.assertRaises(ValueError):
                library.snapshot('my-review')

    def test_invalid_imports_paths_and_reserved_skills(self):
        with tempfile.TemporaryDirectory() as root:
            library = SkillLibrary(root, '学生端')
            for name in ('../escape', 'a/b', 'CON', 'nul', 'a--b', 'course-qa'):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    library.save(name, '说明', '步骤')
            for text in ('plain markdown', '---\nname: a\ndescription: []\n---\nbody',
                         '---\nname: !!python/object/apply:os.system [echo bad]\n---\nbody'):
                with self.assertRaises(ValueError):
                    parse_skill(text)
            with self.assertRaises(ValueError):
                library.save('valid', 'description', 'a' * 25000)
            self.assertEqual(parse_skill(skill_text('valid', 'multi\nline: yes', '步骤'))[1], 'multi\nline: yes')

    def test_builtin_roles_and_bad_file_are_visible(self):
        student = SkillLibrary(Path(__file__).parent, '学生端').snapshot()
        self.assertIn('course-qa', [s.name for s in student])
        self.assertNotIn('admin-qa', [s.name for s in student])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, 'data/user_skills/student/broken')
            path.mkdir(parents=True)
            (path / 'SKILL.md').write_text('invalid', encoding='utf-8')
            library = SkillLibrary(directory, '学生端')
            self.assertTrue(library.list()[1])
            with self.assertRaises(ValueError):
                library.snapshot()


class HarnessTests(unittest.TestCase):
    def context(self, role='学生端'):
        kb = Mock()
        kb.search.return_value = [{'source': '合成循环资料', 'text': 'range(3) 是 0、1、2。', 'reference': '伪造编号'}]
        kb.list.return_value = [{'id': 'a', '来源': '课程', '分类': '课程'}, {'id': 'b', '来源': '内部', '分类': '行政'}]
        return RunContext(kb, role, summary={'学生数': 3}, document_ids=['a'])

    def test_tool_permissions_scopes_and_server_references(self):
        context = self.context()
        tools = {tool.name: tool for tool in build_tools(context)}
        self.assertNotIn('get_learning_summary', tools)
        self.assertIsNone(context.summary)
        self.assertIn('error', tools['search_knowledge'].invoke({'query': '借用', 'category': '行政'}))
        context.knowledge.search.assert_not_called()
        answer = tools['search_knowledge'].invoke({'query': '循环'})
        self.assertEqual(answer['sources'][0]['reference'], '资料1')
        context.knowledge.search.assert_called_once_with('循环', '课程', document_ids=['a'])
        self.assertEqual(len(tools['list_documents'].invoke({})['documents']), 1)
        self.assertIn('get_learning_summary', {t.name for t in build_tools(self.context('教师端'))})

    def test_real_graph_reads_skill_retrieves_and_saves_draft(self):
        endpoint = FakeEndpoint([
            ('', [tool_call('read_file', {'file_path': '/skills/my-review/SKILL.md'}, 'read')]),
            ('', [tool_call('search_knowledge', {'query': '循环'}, 'search')]),
            ('', [tool_call('save_draft', {'title': '复习', 'content': 'range(3) 有三个值。[资料1]'}, 'save')]),
            ('range(3) 是 0、1、2。[资料1]', []),
        ])
        try:
            skill = Skill('my-review', '复习时使用', '先检索，再保存复习草稿。', '自定义')
            result = run_task(ModelConfig(model='deepseek-test-campus', provider='deepseek'), self.context(),
                              [skill], '复习循环', selected=skill.name, model=endpoint.model)
            self.assertEqual(result['loaded_skills'], ['my-review'])
            self.assertEqual(result['model_calls'], 4)
            self.assertEqual(len(result['drafts']), 1)
            self.assertEqual(result['warnings'], [])
            names = {t['function']['name'] for t in endpoint.requests[0]['tools']}
            self.assertTrue({'task', 'execute', 'get_learning_summary'}.isdisjoint(names))
            prompt = str(endpoint.requests[0]['messages'])
            self.assertIn('my-review', prompt)
            self.assertNotIn('先检索，再保存复习草稿。', prompt)
            self.assertIn('先检索，再保存复习草稿。', str(endpoint.requests[1]['messages']))
        finally:
            endpoint.client.close()

    def test_read_only_skills_and_no_host_files(self):
        endpoint = FakeEndpoint([
            ('', [tool_call('write_file', {'file_path': '/skills/my-review/SKILL.md', 'content': 'overwrite'}, 'write')]),
            ('', [tool_call('read_file', {'file_path': '/.env'}, 'read')]),
            ('无法读取配置。', []),
        ])
        try:
            run_task(ModelConfig(model='deepseek-test-campus', provider='deepseek'), self.context(),
                     [Skill('my-review', 'desc', 'original', '自定义')], '测试边界', model=endpoint.model)
            responses = [str(m['content']) for request in endpoint.requests for m in request['messages'] if m['role'] == 'tool']
            self.assertTrue(any('denied' in value.lower() for value in responses))
            self.assertTrue(any('not found' in value.lower() or 'does not exist' in value.lower() for value in responses))
        finally:
            endpoint.client.close()

    def test_limit_and_missing_skill_read_do_not_pass_silently(self):
        from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
        endpoint = FakeEndpoint([('', [tool_call('list_documents', {}, 'list')])])
        try:
            with self.assertRaises(ModelCallLimitExceededError):
                run_task(ModelConfig(model='deepseek-test-campus', provider='deepseek'), self.context(), [],
                         '资料', model=endpoint.model, max_calls=1)
            self.assertEqual(len(endpoint.requests), 1)
        finally:
            endpoint.client.close()
        endpoint = FakeEndpoint([('建议分三天复习。', [])])
        try:
            result = run_task(ModelConfig(model='deepseek-test-campus', provider='deepseek'), self.context(),
                              [Skill('my-review', 'desc', '步骤', '自定义')], '复习', selected='my-review', model=endpoint.model)
            self.assertTrue(result['warnings'])
        finally:
            endpoint.client.close()


class HarnessUITests(unittest.TestCase):
    def test_skill_save_disable_and_task_navigation(self):
        from streamlit.testing.v1 import AppTest
        from test_roles import APP, button
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'CAMPUS_CONFIG_ROOT': root}):
            at = AppTest.from_string(APP, default_timeout=30).run()
            button(at, '进入学生端').click().run()
            at.sidebar.radio[0].set_value('我的技能').run()
            self.assertFalse(at.exception)
            at.text_input(key='skill_学生端_name').set_value('my-study')
            button(at, '保存技能').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(Path(root, 'data/user_skills/student/my-study/SKILL.md').exists())
            at.selectbox(key='skill_editor_choice_学生端').set_value('my-study').run()
            button(at, '试运行此技能').click().run()
            self.assertFalse(at.exception)
            self.assertEqual(at.session_state['workspace_nav'], '智能任务')
            self.assertEqual(at.selectbox(key='smart_skill_学生端').value, 'my-study')
            self.assertTrue(button(at, '开始执行').disabled)
            at.sidebar.radio[0].set_value('我的技能').run()
            at.checkbox(key='skill_学生端_enabled').uncheck()
            button(at, '保存技能').click().run()
            self.assertEqual(SkillLibrary(root, '学生端').snapshot(), [])

    def test_success_then_error_keeps_result_and_inputs(self):
        from streamlit.testing.v1 import AppTest
        from test_roles import APP, button
        result = {'answer': '已生成学习建议', 'warnings': [], 'model_calls': 1, 'total_tokens': 20,
                  'sources': [], 'drafts': [], 'events': [], 'todos': [], 'loaded_skills': []}
        with tempfile.TemporaryDirectory() as root, patch.dict('os.environ', {'CAMPUS_CONFIG_ROOT': root}):
            online_app = APP.replace("os.environ['CAMPUS_CHAT_MODE'] = 'offline'", "os.environ['CAMPUS_CHAT_MODE'] = 'project'")
            online_app = online_app.replace('lambda root: ModelConfig()', "lambda root: ModelConfig(mode='本地模型')")
            at = AppTest.from_string(online_app, default_timeout=30).run()
            button(at, '进入学生端').click().run()
            at.sidebar.radio[0].set_value('智能任务').run()
            at.text_area(key='smart_prompt_学生端').set_value('制定学习计划')
            with patch('campus_agent_page.run_task', return_value=result):
                button(at, '开始执行').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(any(m.value == '已生成学习建议' for m in at.markdown))
            with patch('campus_agent_page.run_task', side_effect=RuntimeError('secret-token')):
                button(at, '开始执行').click().run()
            self.assertFalse(at.exception)
            self.assertTrue(at.error)
            self.assertNotIn('secret-token', at.error[0].value)
            self.assertEqual(at.text_area(key='smart_prompt_学生端').value, '制定学习计划')


if __name__ == '__main__':
    unittest.main()
