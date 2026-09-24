import hashlib
import unittest
from unittest.mock import MagicMock

from campus_embeddings import EmbeddingConfig
from campus_milvus import MilvusSettings
from campus_personal_milvus import StudentMilvus, PersistentPersonalKnowledge, student_settings


class FakeLibrary:
    def __init__(self):
        self.docs = {}

    def list(self):
        return [{'id': ident, '来源': doc['name'], '分类': '课程', '字符数': len(doc['text'])}
                for ident, doc in self.docs.items()]

    def add(self, name, category, text):
        ident = hashlib.sha256(('课程\n'+text).encode()).hexdigest()
        if ident in self.docs:
            return False
        self.docs[ident] = {'name': name, 'text': text}
        return True

    def read_text(self, ident):
        return self.docs[ident]['text']

    def delete(self, ident):
        del self.docs[ident]


TEST_LIBRARY = FakeLibrary()


class PersistentTests(unittest.TestCase):
    def test_collection_separate_valid_and_stable(self):
        for name in ['campus_docs_v1', 'a'*255]:
            original = MilvusSettings(collection=name)
            derived = student_settings(original)
            self.assertNotEqual(derived.collection, name)
            self.assertLessEqual(len(derived.collection), 255)
            self.assertEqual(derived.database, original.database)
            self.assertEqual(derived, student_settings(original))

    def test_recreated_adapter_loads_and_deletes_persistent_document(self):
        backend = FakeLibrary()
        first = PersistentPersonalKnowledge(backend)
        ident, added = first.add('notes.txt', 'persistent notes')
        self.assertTrue(added)
        second = PersistentPersonalKnowledge(backend)
        self.assertIn(ident, second.documents)
        self.assertEqual(second.read(ident), 'persistent notes')
        self.assertFalse(second.add('notes.txt', 'persistent notes')[1])
        second.delete(ident)
        self.assertEqual(PersistentPersonalKnowledge(backend).documents, {})

    def test_no_silent_fallback_and_no_unscoped_search(self):
        backend = MagicMock()
        backend.add.side_effect = RuntimeError('embedding failed')
        store = PersistentPersonalKnowledge(backend)
        with self.assertRaises(RuntimeError):
            store.add('test.txt', 'notes')
        self.assertEqual(store.search('question','课程', document_ids=[]), [])
        backend.search.assert_not_called()
        store.search('question','课程', document_ids=['chosen'])
        backend.search.assert_called_once_with('question', '课程', 4, document_ids=['chosen'])

    def test_read_text_orders_chunks_removes_overlap(self):
        client = MagicMock()
        kb = StudentMilvus(student_settings(MilvusSettings()), EmbeddingConfig(), client=client)
        kb._ready = True
        original = 'a'*700 + 'b'*700 + 'c'*120
        rows = [{'chunk_id':i, 'text':original[start:start+800]} for i,start in enumerate(range(0,len(original),700))]
        kb._manifests = MagicMock(return_value=[{'document_id':'doc', 'total_chars':len(original), 'chunk_count':len(rows)}])
        iterator = MagicMock()
        iterator.next.side_effect = [list(reversed(rows)), []]
        client.query_iterator.return_value = iterator
        self.assertEqual(kb.read_text('doc'), original)
        self.assertIn('document_id == "doc"', client.query_iterator.call_args.kwargs['filter'])
        iterator.close.assert_called_once()

    def test_missing_document_cannot_read_chunks(self):
        client = MagicMock()
        kb = StudentMilvus(student_settings(MilvusSettings()), EmbeddingConfig(), client=client)
        kb._manifests = MagicMock(return_value=[])
        with self.assertRaises(ValueError):
            kb.read_text('unknown')
        client.query_iterator.assert_not_called()

    def test_ui_storage_switch_and_new_session(self):
        from streamlit.testing.v1 import AppTest
        from test_roles import APP, button
        from campus_personal import PersonalKnowledge
        TEST_LIBRARY.docs.clear()
        persistent = PersistentPersonalKnowledge(TEST_LIBRARY)
        ident, _ = persistent.add('persistent.txt','persistent document')
        app_code = APP.replace('app.main()', "from test_personal_milvus import TEST_LIBRARY\nimport campus_personal_page\ncampus_personal_page.persistent_connection = lambda settings, embedding: TEST_LIBRARY\napp.main()")
        at = AppTest.from_string(app_code, default_timeout=20).run()
        button(at, '进入学生端').click().run()
        local = PersonalKnowledge()
        local.add('session.txt', 'session document')
        at.session_state['campus_workspace']['personal_documents'] = local
        at.sidebar.radio[0].set_value('我的资料').run()
        self.assertIn('session.txt', at.selectbox(key='personal_file_select').options[0])
        at.radio(key='personal_storage_choice').set_value('长期保存').run()
        self.assertFalse(at.exception)
        self.assertEqual(at.selectbox(key='personal_file_select').value, ident)
        button(at, '围绕这份文件提问').click().run()
        self.assertEqual(at.radio(key='personal_storage_choice').value, '长期保存')
        self.assertEqual(at.selectbox(key='personal_qa_select').value, ident)
        other = AppTest.from_string(app_code, default_timeout=20).run()
        button(other, '进入学生端').click().run()
        other.sidebar.radio[0].set_value('我的资料').run()
        self.assertEqual(len(other.selectbox), 0)
        other.radio(key='personal_storage_choice').set_value('长期保存').run()
        self.assertFalse(other.exception)
        self.assertEqual(other.selectbox(key='personal_file_select').value, ident)
        TEST_LIBRARY.docs.clear()


if __name__ == '__main__':
    unittest.main()
