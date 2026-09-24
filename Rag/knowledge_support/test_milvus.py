"""Milvus boundary tests; mocks verify calls, no external database needed."""
import unittest
from unittest.mock import MagicMock
from pymilvus import DataType
from campus_embeddings import EmbeddingConfig
from campus_milvus import MilvusKnowledge, MilvusSettings


class MilvusTests(unittest.TestCase):
    def setUp(self):
        self.client = MagicMock()
        self.client.has_collection.return_value = True
        self.client.describe_collection.return_value = {'auto_id':False,'enable_dynamic_field':True,'fields':[
            {'name':'id','type':DataType.VARCHAR,'is_primary':True},
            {'name':'vector','type':DataType.FLOAT_VECTOR,'params':{'dim':3}}]}
        self.client.list_indexes.return_value = ['vector']
        self.client.describe_index.return_value = {'field_name':'vector','metric_type':'COSINE'}
        self.client.get.return_value = []
        self.embedder = MagicMock()
        self.embedder.embed.return_value = [[1.,0.,0.]]
        self.kb = MilvusKnowledge(MilvusSettings(dimension=3), EmbeddingConfig(), self.client, self.embedder)

    def manifests(self, rows):
        iterator = MagicMock()
        iterator.next.side_effect = [rows, []] if rows else [[]]
        self.client.query_iterator.return_value = iterator
        return iterator

    def test_search_uses_milvus_client_and_scoped_filter(self):
        iterator = self.manifests([{'document_id':'abc'}])
        self.client.search.return_value = [[{'distance':0.9,'entity':{'source':'合成','text':'循环结构','chunk_id':0}}]]
        result = self.kb.client_search('循环', '课程')
        self.assertEqual(result[0]['reference'],'资料1')
        args = self.client.search.call_args.kwargs
        self.assertEqual(args['data'], [[1.,0.,0.]])
        self.assertEqual(args['search_params']['metric_type'], 'COSINE')
        self.assertIn('record_type == "chunk"',args['filter'])
        self.assertIn('category == "课程"',args['filter'])
        self.assertIn('document_id in ["abc"]',args['filter'])
        iterator.close.assert_called_once()

    def test_no_document_does_not_embed(self):
        self.manifests([])
        self.assertEqual(self.kb.search('问题','课程'),[])
        self.embedder.embed.assert_not_called()
        self.client.search.assert_not_called()

    def test_failed_chunks_do_not_write_commit_marker(self):
        self.client.upsert.side_effect = RuntimeError('write failed')
        with self.assertRaises(RuntimeError):
            self.kb.add('test','课程','循环结构')
        rows = self.client.upsert.call_args.kwargs['data']
        self.assertTrue(all(row['record_type']=='chunk' for row in rows))
        self.assertEqual(self.client.upsert.call_count,1)

    def test_existing_document_does_not_reembed(self):
        self.client.get.return_value = [{'id':'committed'}]
        self.assertFalse(self.kb.add('test','课程','循环'))
        self.embedder.embed.assert_not_called()

    def test_migration_reuses_vectors_and_commits_last(self):
        self.assertTrue(self.kb.import_document('test','课程','循环',[('循环',[1.,0.,0.])]))
        self.embedder.embed.assert_not_called()
        self.assertEqual(self.client.upsert.call_args_list[-1].kwargs['data'][0]['record_type'],'manifest')

    def test_dimension_mismatch_never_inserts(self):
        self.embedder.embed.return_value = [[1.,0.]]
        with self.assertRaises(ValueError):
            self.kb.add('test','课程','循环')
        self.client.upsert.assert_not_called()

    def test_delete_hides_manifest_before_chunks(self):
        self.kb.delete('abc')
        self.assertIn('ids',self.client.delete.call_args_list[0].kwargs)
        self.assertIn('document_id == "abc"',self.client.delete.call_args_list[1].kwargs['filter'])

    def test_incompatible_collection_never_overwritten(self):
        self.client.describe_collection.return_value['fields'][1]['params']['dim'] = 2
        with self.assertRaises(ValueError):
            self.kb.add('test','课程','循环')
        self.client.create_collection.assert_not_called()
        self.client.upsert.assert_not_called()


if __name__ == '__main__':
    unittest.main()
