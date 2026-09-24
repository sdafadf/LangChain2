"""Offline business, security and Streamlit regression tests; no real student data."""
import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from campus_core import (DEMO_DOCS, DEMO_GRADES, LocalKnowledge, analyze_grades,
                         office_draft, parse_grades, redact, safe_csv)
from campus_engine import CampusCoordinator, ModelConfig, generate


class BusinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.kb = LocalKnowledge(Path(self.tmp.name) / 'test.db')
        for doc in DEMO_DOCS:
            self.kb.add(*doc)
        self.engine = CampusCoordinator(self.kb)

    def tearDown(self):
        self.tmp.cleanup()

    def test_weighted_statistics(self):
        rows = parse_grades(DEMO_GRADES.encode())
        report = analyze_grades(rows)
        self.assertEqual(report['学生数'], 4)
        self.assertEqual(report['记录数'], 12)
        self.assertEqual(report['总得分率%'], 67.5)
        self.assertEqual(report['知识点'][0]['知识点'], '函数参数')
        self.assertEqual(report['知识点'][0]['得分率%'], 55)
        self.assertTrue(report['知识点'][0]['需关注'])
        rows = parse_grades('学生编号,知识点,得分,满分\nS1,A,1,1\nS2,A,0,9'.encode())
        self.assertEqual(analyze_grades(rows)['总得分率%'], 10)

    def test_bad_grades(self):
        cases = ['', '学生编号,知识点,得分,满分\n', '姓名,知识点,得分,满分\n甲,A,1,1',
                 '学生编号,知识点,得分,满分\nS1,A,nan,10',
                 '学生编号,知识点,得分,满分\nS1,A,1,0',
                 '学生编号,知识点,得分,满分\nS1,A,11,10',
                 '学生编号,知识点,得分,满分\nS1,A,,10',
                 '学生编号,知识点,得分,满分\nS1,A,-1,10',
                 '学生编号,知识点,得分,满分\nS1,A,1,10,extra',
                 '学生编号,知识点,得分,满分\n真实姓名,A,1,10']
        for raw in cases:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_grades(raw.encode())

    def test_duplicates_need_explicit_choice(self):
        raw = '学生编号,知识点,得分,满分\nS1,A,1,10\nS1,A,2,10'.encode()
        with self.assertRaises(ValueError):
            parse_grades(raw)
        self.assertEqual(len(parse_grades(raw, True)), 2)

    def test_kb_isolation_dedup_delete(self):
        self.assertFalse(self.kb.add(*DEMO_DOCS[0]))
        self.assertTrue(self.kb.search('循环结构', '课程'))
        self.assertFalse(self.kb.search('循环结构', '行政'))
        self.assertTrue(self.kb.search('设备借用', '行政'))
        self.assertEqual(len(self.kb.list()), 5)
        self.kb.delete(self.kb.list()[0]['id'])
        self.assertEqual(len(self.kb.list()), 4)

    def test_offline_never_calls_model(self):
        with patch('campus_engine.generate', side_effect=AssertionError('must stay offline')):
            result = self.engine.ask('设备借用需要哪些材料', '行政')
            self.assertIn('原文', result['answer'])
            self.assertTrue(result['sources'])
            self.assertIn('待确认', self.engine.office('会议纪要与待办', '准备资料。')['answer'])

    def test_no_evidence_never_calls_model(self):
        engine = CampusCoordinator(self.kb, ModelConfig('本地模型'))
        with patch('campus_engine.generate', side_effect=AssertionError('no evidence')):
            result = engine.ask('量子纠缠', '课程')
            self.assertFalse(result['sources'])
            self.assertIn('无法', result['answer'])

    def test_model_boundaries(self):
        for config in [ModelConfig('本地模型', 'http://example.com/v1'),
                       ModelConfig('本地模型', 'http://localhost:11434/v1?secret=a'),
                       ModelConfig('云端模型', 'https://example.com/v1', cloud_consent=False),
                       ModelConfig('云端模型', 'http://example.com/v1', cloud_consent=True)]:
            with self.subTest(config=config), self.assertRaises(ValueError):
                config.validate()
        ModelConfig('本地模型').validate()

    def test_failure_does_not_fallback(self):
        engine = CampusCoordinator(self.kb, ModelConfig('本地模型'))
        with patch('campus_engine.generate', side_effect=ConnectionError('offline')) as model:
            with self.assertRaises(ConnectionError):
                engine.ask('循环结构', '课程')
            self.assertEqual(model.call_count, 1)

    def test_real_langchain_adapter_with_mock_http(self):
        """Exercise actual SDK serialization without a network or real LLM."""
        import httpx
        original_client = httpx.Client
        requests = []
        def reply(request):
            requests.append(request)
            return httpx.Response(200, json={
                'id': 'synthetic', 'object': 'chat.completion', 'created': 0, 'model': 'synthetic',
                'choices': [{'index': 0, 'message': {'role': 'assistant', 'content': '合成模型响应[资料1]'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 1, 'completion_tokens': 1, 'total_tokens': 2}})
        class MockClient(original_client):
            def __init__(self, **kwargs):
                super().__init__(transport=httpx.MockTransport(reply), **kwargs)
        with patch('httpx.Client', MockClient):
            answer = generate(ModelConfig('本地模型'), '只用证据回答', '合成输入')
        self.assertEqual(answer, '合成模型响应[资料1]')
        self.assertEqual(requests[0].url.host, '127.0.0.1')
        self.assertEqual(json.loads(requests[0].content)['messages'][-1]['content'], '合成输入')

    def test_safe_exports(self):
        result = safe_csv([{'知识点': ' =1+1', '姓名': '不得导出'}], ['知识点']).decode('utf-8-sig')
        self.assertIn("' =1+1", result)
        self.assertNotIn('不得导出', result)
        self.assertNotIn('13800138000', redact('联系 13800138000 或 demo@example.com'))
        self.assertIn('邮箱已隐藏', redact('demo@example.com'))

    def test_office_no_invented_owner(self):
        self.assertIn('待确认', office_draft('会议纪要与待办', '准备教学材料。'))
        with self.assertRaises(ValueError):
            office_draft('通知草稿', '')


class UITests(unittest.TestCase):
    def test_full_offline_flow(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CAMPUS_CHAT_MODE': 'offline'}), patch(
                'campus_app.MilvusKnowledge', return_value=LocalKnowledge(Path(tmp)/'ui-fixture.db')):
            from campus_app import get_knowledge
            get_knowledge.clear()
            app = AppTest.from_file(str(Path(__file__).with_name('app.py')), default_timeout=30).run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == '进入教师端').click().run()
            next(r for r in app.radio if r.label == '工作空间').set_value('学情分析').run()
            next(r for r in app.radio if r.label == '数据来源').set_value('合成样例').run()
            next(b for b in app.button if b.label == '分析学情').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(app.metric[0].value, '4')
            next(b for b in app.button if b.label == '带入学情，继续教学设计').click().run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == '采用本地规则建议').click().run()
            self.assertFalse(app.exception)
            next(r for r in app.radio if r.label == '草稿视图').set_value('编辑').run()
            next(t for t in app.text_area if t.label == '审核与编辑').set_value('已审核的教学草稿').run()
            next(r for r in app.radio if r.label == '工作空间').set_value('教学首页').run()
            self.assertEqual(next(t for t in app.text_area if t.label == '审核与编辑').value,'已审核的教学草稿')
            next(r for r in app.radio if r.label == '工作空间').set_value('学情分析').run()
            self.assertIn('grade_result',app.session_state.campus_workspace)
            next(r for r in app.radio if r.label == '工作空间').set_value('教学资料').run()
            next(b for b in app.button if b.label == '添加合成演示资料').click().run()
            self.assertFalse(app.exception)
            next(b for b in app.button if b.label == '切换身份').click().run()
            next(b for b in app.button if b.label == '进入学生端').click().run()
            next(r for r in app.radio if r.label == '工作空间').set_value('课程答疑').run()
            next(b for b in app.button if b.label == 'for 和 while 循环有什么区别？').click().run()
            self.assertEqual(len(app.chat_message), 2)
            self.assertFalse(app.exception)
            next(s for s in app.selectbox if s.label=='学习方式').set_value('提示引导').run()
            next(r for r in app.radio if r.label=='工作空间').set_value('学习首页').run()
            next(r for r in app.radio if r.label=='工作空间').set_value('课程答疑').run()
            self.assertEqual(next(s for s in app.selectbox if s.label=='学习方式').value,'提示引导')
            next(b for b in app.button if b.label == '切换身份').click().run()
            next(b for b in app.button if b.label == '进入教师端').click().run()
            next(r for r in app.radio if r.label == '工作空间').set_value('办公工具').run()
            next(r for r in app.radio if r.label == '办公任务').set_value('会议纪要与待办').run()
            next(b for b in app.button if b.label == '填入合成示例').click().run()
            next(b for b in app.button if b.label == '生成办公草稿').click().run()
            self.assertFalse(app.exception)
            self.assertIn('待办候选', app.session_state.campus_workspace['drafts'][0]['content'])
            office_text = next(t for t in app.text_area if t.label=='会议记录或通知要点').value
            next(r for r in app.radio if r.label=='工作空间').set_value('教学首页').run()
            next(r for r in app.radio if r.label=='工作空间').set_value('办公工具').run()
            next(r for r in app.radio if r.label=='办公任务').set_value('会议纪要与待办').run()
            self.assertEqual(next(t for t in app.text_area if t.label=='会议记录或通知要点').value,office_text)
            next(b for b in app.button if b.label == '系统设置').click().run()
            self.assertFalse(app.exception)
            next(s for s in app.selectbox if s.label == '运行模式').set_value('本地模型').run()
            self.assertEqual(app.session_state.campus_workspace['model_config'].mode,'离线工具')
            next(b for b in app.button if b.label == '应用生成设置').click().run()
            self.assertEqual(app.session_state.campus_workspace['model_config'].mode,'本地模型')
            self.assertFalse(app.exception)
            get_knowledge.clear()


if __name__ == '__main__':
    unittest.main()
