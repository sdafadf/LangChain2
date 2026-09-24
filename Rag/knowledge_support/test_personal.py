import unittest
from unittest.mock import Mock
from campus_personal import PersonalKnowledge, PersonalSearch
from campus_engine import CampusCoordinator, ModelConfig


class PersonalTests(unittest.TestCase):
    def test_session_isolation_dedup_delete(self):
        first, second = PersonalKnowledge(), PersonalKnowledge()
        ident, added = first.add('notes.txt', '循环笔记')
        self.assertTrue(added)
        self.assertFalse(first.add('renamed.txt', '循环笔记')[1])
        self.assertEqual(second.documents, {})
        first.delete(ident)
        self.assertEqual(first.documents, {})

    def test_selection_cache_and_model_change(self):
        store = PersonalKnowledge()
        ident, _ = store.add('mine.txt', '循环与条件判断')
        store.add('other.txt', '不应检索其他文件')
        embedder = Mock()
        embedder.embed.side_effect = lambda texts: [[1.0, 0.0] for _ in texts]
        search = PersonalSearch(store, embedder, 'model1')
        self.assertEqual(search.search('循环', '课程', document_ids=[]), [])
        embedder.embed.assert_not_called()
        result = CampusCoordinator(search, ModelConfig()).ask('循环', '课程', document_ids=[ident])
        self.assertIn('mine.txt', result['answer'])
        self.assertEqual(len(embedder.embed.call_args_list), 2)
        search.search('循环', '课程', document_ids=[ident])
        self.assertEqual(len(embedder.embed.call_args_list), 3)
        PersonalSearch(store, embedder, 'model2').search('循环', '课程', document_ids=[ident])
        self.assertEqual(len(embedder.embed.call_args_list), 5)
        self.assertNotIn('不应检索其他文件', str(embedder.embed.call_args_list))
        store.delete(ident)
        self.assertEqual(search.search('循环', '课程', document_ids=[ident]), [])

    def test_embedding_failure_keeps_file_and_no_partial_index(self):
        store = PersonalKnowledge()
        ident, _ = store.add('notes.txt', '笔记')
        embedder = Mock()
        embedder.embed.side_effect = [[[1.0, 0.0]], RuntimeError('offline')]
        with self.assertRaises(RuntimeError):
            PersonalSearch(store, embedder, 'model1').search('问题', '课程', document_ids=[ident])
        self.assertEqual(store.documents[ident]['text'], '笔记')
        self.assertIsNone(store.documents[ident]['vectors'])

    def test_limits(self):
        store = PersonalKnowledge()
        for body in ['', ' '*5, 'a'*200001]:
            with self.assertRaises(ValueError):
                store.add('invalid.txt', body)
        for i in range(10):
            store.add(f'{i}.txt', str(i))
        with self.assertRaises(ValueError):
            store.add('extra.txt', 'extra')

    def test_personal_page_handoff_and_delete(self):
        from streamlit.testing.v1 import AppTest
        from test_roles import APP, button
        at = AppTest.from_string(APP, default_timeout=20).run()
        button(at, '进入学生端').click().run()
        store = PersonalKnowledge()
        ident, _ = store.add('my-notes.txt', '我的循环笔记')
        at.session_state['campus_workspace']['personal_documents'] = store
        at.sidebar.radio[0].set_value('我的资料').run()
        self.assertFalse(at.exception)
        self.assertEqual(len(at.get('file_uploader')), 1)
        button(at, '围绕这份文件提问').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(at.radio(key='student_qa_source').value, '我的资料')
        self.assertEqual(at.selectbox(key='personal_qa_select').value, ident)
        at.session_state['campus_workspace']['personal_qa'][ident] = [{'role':'user','content':'旧问题'}]
        at.sidebar.radio[0].set_value('我的资料').run()
        next(c for c in at.checkbox if '确认删除文件' in c.label).check().run()
        button(at, '删除个人文件').click().run()
        self.assertFalse(at.exception)
        self.assertEqual(store.documents, {})
        self.assertNotIn(ident, at.session_state['campus_workspace']['personal_qa'])


if __name__ == '__main__':
    unittest.main()
