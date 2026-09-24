"""Run the current campus regression suite without external services."""
import unittest

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromNames(['test_campus', 'test_embeddings', 'test_chat_config', 'test_milvus', 'test_workspace.WorkspaceTests', 'test_workspace.ScopedMilvusTests.test_explicit_empty_scope_never_searches_all_documents', 'test_workspace.ScopedMilvusTests.test_selected_scope_restricts_server_filter'])
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_practice'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_roles'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_personal'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_personal_milvus'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_experience'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_composition'))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromName('test_harness'))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    raise SystemExit(not result.wasSuccessful())
