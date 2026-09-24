import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campus_core import LocalKnowledge
from campus_embeddings import EmbeddingConfig, VectorKnowledge


class FakeEmbedder:
    def embed(self, texts):
        return [[1., 0.] if '循环' in text else [0., 1.] for text in texts]


class EmbeddingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'kb.db'
        self.config = EmbeddingConfig()
        self.kb = VectorKnowledge(self.path, self.config, FakeEmbedder())

    def tearDown(self):
        self.temp.cleanup()

    def test_upload_query_dedup_and_category(self):
        self.assertTrue(self.kb.add('课程.txt', '课程', '循环结构'))
        self.assertFalse(self.kb.add('改名.txt', '课程', '循环结构'))
        self.kb.add('行政.txt', '行政', '设备借用')
        self.assertEqual(self.kb.search('循环如何使用', '课程')[0]['text'], '循环结构')
        self.assertFalse(self.kb.search('循环如何使用', '行政'))

    def test_legacy_documents_require_index_and_model_isolation(self):
        LocalKnowledge(self.path).add('旧资料', '课程', '循环结构')
        with self.assertRaises(ValueError):
            self.kb.search('循环', '课程')
        self.assertEqual(self.kb.index_pending(), 1)
        other = VectorKnowledge(self.path, EmbeddingConfig(model='another'), FakeEmbedder())
        self.assertEqual(len(other.pending()), 1)
        self.assertTrue(self.kb.search('循环', '课程'))

    def test_failed_embedding_does_not_store_partial_document(self):
        with patch.object(self.kb.embedder, 'embed', side_effect=ConnectionError):
            with self.assertRaises(ConnectionError):
                self.kb.add('资料', '课程', '循环')
        self.assertFalse(self.kb.list())

    def test_invalid_dimensions_and_delete(self):
        self.kb.add('资料', '课程', '循环')
        with patch.object(self.kb.embedder, 'embed', return_value=[[1., 0., 0.]]):
            with self.assertRaises(ValueError):
                self.kb.search('循环', '课程')
        self.kb.delete(self.kb.list()[0]['id'])
        with self.kb.connect() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM campus_vectors').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
