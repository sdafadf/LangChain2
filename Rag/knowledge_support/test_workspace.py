import unittest
from unittest.mock import MagicMock, patch
from campus_engine import CampusCoordinator, ModelConfig
from campus_workspace import make_draft, input_fingerprint, focus_topics
from test_milvus import MilvusTests


class WorkspaceTests(unittest.TestCase):
    def test_answer_preferences_reach_prompt_and_scope(self):
        kb = MagicMock()
        kb.search.return_value = [{'reference':'资料1','source':'合成','text':'函数返回值'}]
        engine = CampusCoordinator(kb,ModelConfig('本地模型'))
        with patch('campus_engine.generate',return_value='说明[资料1]') as generate:
            result = engine.ask('函数如何返回', '课程',document_ids=['selected'],response_style='提示引导')
        kb.search.assert_called_once_with('函数如何返回','课程',document_ids=['selected'])
        self.assertIn('帮助学生自己推导',generate.call_args.args[1])
        self.assertEqual(len(result['sources']),1)

    def test_invalid_style_never_queries(self):
        kb=MagicMock()
        with self.assertRaises(ValueError):
            CampusCoordinator(kb).ask('问题','课程',response_style='未知')
        kb.search.assert_not_called()

    def test_result_lineage_changes_with_data_and_rules(self):
        original = input_fingerprint(b'a',False,60)
        self.assertNotEqual(original,input_fingerprint(b'b',False,60))
        self.assertNotEqual(original,input_fingerprint(b'a',True,60))
        self.assertNotEqual(original,input_fingerprint(b'a',False,70))
        draft = make_draft('教学','教学','内容',original)
        self.assertEqual(draft['source_signature'],original)
        self.assertEqual(focus_topics({'知识点':[{'知识点':'函数','需关注':True}]}),'函数')


class ScopedMilvusTests(MilvusTests):
    def test_explicit_empty_scope_never_searches_all_documents(self):
        self.manifests([{'document_id':'abc'}])
        self.assertEqual(self.kb.client_search('循环','课程',document_ids=[]),[])
        self.embedder.embed.assert_not_called()
        self.client.search.assert_not_called()

    def test_selected_scope_restricts_server_filter(self):
        self.manifests([{'document_id':'abc'},{'document_id':'other'}])
        self.client.search.return_value = [[]]
        self.kb.client_search('循环','课程',document_ids=['abc'])
        condition = self.client.search.call_args.kwargs['filter']
        self.assertIn('document_id in ["abc"]',condition)
        self.assertNotIn('other',condition)


if __name__ == '__main__':
    unittest.main()
