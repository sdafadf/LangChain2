"""补练验收：数据边界、单次出题、反馈重算与完整页面流程。"""
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from campus_core import LocalKnowledge
from campus_engine import ModelConfig
from campus_practice import (MAX_BYTES, demo_pack, dump_feedback, dump_pack, feedback_rows,
                             generate_pack, load_feedback, load_pack, pack_id, progress, submit,
                             validate_pack)


class PracticeTests(unittest.TestCase):
    def test_pack_roundtrip_does_not_trust_approval_or_extra_fields(self):
        pack = demo_pack()
        raw = dict(pack, approved=True, student_name='not retained')
        loaded = load_pack(json.dumps(raw).encode())
        self.assertEqual(loaded, pack)
        self.assertEqual(load_pack(dump_pack(pack)), pack)

    def test_invalid_question_shapes_are_rejected(self):
        for field, value in [('answer', True), ('answer', -1), ('answer', 4),
                             ('options', ['a'] * 4), ('options', 'abcd'),
                             ('references', ['invented']), ('stem', ''), ('hint', ['bad'])]:
            with self.subTest(field=field, value=value):
                pack = demo_pack()
                pack['questions'][0][field] = value
                with self.assertRaises(ValueError):
                    validate_pack(pack)

    def test_file_size_encoding_and_version(self):
        for content in [b'', b'x' * (MAX_BYTES + 1), b'\xff', b'null', b'{}',
                        json.dumps(dict(demo_pack(), version=True)).encode()]:
            with self.subTest(content=content[:40]), self.assertRaises(ValueError):
                load_pack(content)

    def test_no_evidence_never_generates(self):
        knowledge = MagicMock()
        knowledge.search.return_value = []
        with patch('campus_engine.generate') as model, self.assertRaises(ValueError):
            generate_pack(knowledge, ModelConfig('本地模型'), '循环结构', ['course'])
        model.assert_not_called()
        knowledge.search.assert_called_once_with('循环结构 基础概念 常见错误 练习', '课程', document_ids=['course'])

    def test_model_generates_once_and_cannot_forge_sources(self):
        knowledge = MagicMock()
        sample = demo_pack()
        knowledge.search.return_value = sample['sources']
        response = json.dumps({'questions': sample['questions'], 'sources': [{'fake': 'ignored'}]})
        with patch('campus_engine.generate', return_value=response) as model:
            pack = generate_pack(knowledge, ModelConfig('本地模型'), '循环结构', ['course'])
        self.assertEqual(model.call_count, 1)
        self.assertEqual(pack['sources'], sample['sources'])
        self.assertEqual(pack['origin'], '课程资料')

    def test_invalid_model_output_never_becomes_pack(self):
        kb = MagicMock()
        kb.search.return_value = demo_pack()['sources']
        for response in ['not json', '[]', '{"questions":[]}']:
            with patch('campus_engine.generate', return_value=response), self.assertRaises(ValueError):
                generate_pack(kb, ModelConfig('本地模型'), '循环结构')

    def test_sequential_attempts_and_two_try_limit(self):
        pack = demo_pack()
        with self.assertRaises(ValueError):
            submit(pack, [[], []], 1, 2)
        attempts = submit(pack, [[], []], 0, 0)
        self.assertFalse(progress(pack, attempts)[0]['done'])
        attempts = submit(pack, attempts, 0, 1)
        self.assertTrue(progress(pack, attempts)[0]['correct'])
        with self.assertRaises(ValueError):
            submit(pack, attempts, 0, 1)
        attempts = submit(pack, attempts, 1, 0)
        attempts = submit(pack, attempts, 1, 1)
        self.assertTrue(progress(pack, attempts)[1]['done'])
        self.assertFalse(progress(pack, attempts)[1]['correct'])
        self.assertEqual(feedback_rows(pack, attempts)[0]['首次答对'], False)

    def test_feedback_recalculated_and_version_bound(self):
        pack = demo_pack()
        encoded = dump_feedback(pack, [[0, 1], [2]])
        forged = json.loads(encoded)
        forged['score'] = 999
        self.assertEqual(load_feedback(json.dumps(forged).encode(), pack), [[0, 1], [2]])
        changed = copy.deepcopy(pack)
        changed['questions'][0]['hint'] = '新的提示'
        self.assertNotEqual(pack_id(pack), pack_id(changed))
        with self.assertRaises(ValueError):
            load_feedback(encoded, changed)
        for attempts in [[[1, 1], []], [[], [2]], [[0, 0, 1], []], [[True], []]]:
            forged['attempts'] = attempts
            with self.assertRaises(ValueError):
                load_feedback(json.dumps(forged).encode(), pack)


class PracticeUITests(unittest.TestCase):
    def test_teacher_student_feedback_and_changed_review(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'CAMPUS_CHAT_MODE': 'offline'}), patch(
                'campus_app.MilvusKnowledge', return_value=LocalKnowledge(Path(temp) / 'fixture.db')):
            from campus_app import get_knowledge
            get_knowledge.clear()
            self.addCleanup(get_knowledge.clear)
            app = AppTest.from_file(str(Path(__file__).with_name('app.py')), default_timeout=30).run()

            def radio(label, value):
                next(item for item in app.radio if item.label == label).set_value(value).run()
                self.assertFalse(app.exception)

            def button(label):
                next(item for item in app.button if item.label == label).click().run()
                self.assertFalse(app.exception)

            button('进入教师端')
            radio('工作空间', '学情分析')
            radio('数据来源', '合成样例')
            button('分析学情')
            radio('工作空间', '备课与练习')
            radio('准备任务', '练习与反馈')
            next(item for item in app.selectbox if item.label == '补练知识点').set_value('循环结构').run()
            radio('题目来源', '合成演示')
            button('准备循环边界演示题')
            approve_label = '已核对题目、答案与依据，确认不含个人身份和学校信息'
            self.assertTrue(next(b for b in app.button if b.label == '审核通过，启用补练').disabled)
            next(c for c in app.checkbox if c.label == approve_label).check().run()
            button('审核通过，启用补练')
            original_id = app.session_state.campus_workspace['practice_active_id']

            button('切换身份')
            button('进入学生端')
            radio('工作空间', '我的练习')
            radio('选择答案', 0)
            button('提交本题答案')
            self.assertTrue(any('首次作答未正确' in w.value for w in app.warning))
            self.assertFalse(any('参考答案：' in m.value for m in app.markdown))
            radio('选择答案', 1)
            button('提交本题答案')
            radio('选择答案', 2)
            button('提交本题答案')
            self.assertEqual(app.session_state.campus_workspace['practice_attempts'], [[0, 1], [2]])
            self.assertTrue(any('两道练习已完成' in s.value for s in app.success))
            pack = app.session_state.campus_workspace['practice_active']
            self.assertEqual(load_feedback(dump_feedback(pack, [[0, 1], [2]]), pack), [[0, 1], [2]])

            button('切换身份')
            button('进入教师端')
            radio('工作空间', '备课与练习')
            radio('准备任务', '练习与反馈')
            next(t for t in app.text_area if t.label == '首次答错后的提示').set_value('先手动列出循环变量，再判断边界。').run()
            self.assertTrue(next(b for b in app.button if b.label == '审核通过，启用补练').disabled)
            self.assertEqual(app.session_state.campus_workspace['practice_active_id'], original_id)
            next(c for c in app.checkbox if c.label == approve_label).check().run()
            button('审核通过，启用补练')
            self.assertNotEqual(app.session_state.campus_workspace['practice_active_id'], original_id)
            self.assertEqual(app.session_state.campus_workspace['practice_attempts'], [[], []])

            radio('工作空间', '学情分析')
            app.slider[0].set_value(70).run()
            radio('工作空间', '备课与练习')
            radio('准备任务', '练习与反馈')
            self.assertTrue(any('学情已变化' in w.value for w in app.warning))
            self.assertTrue(next(b for b in app.button if b.label == '审核通过，启用补练').disabled)


if __name__ == '__main__':
    unittest.main()
