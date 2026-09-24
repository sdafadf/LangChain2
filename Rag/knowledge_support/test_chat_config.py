import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from campus_engine import ModelConfig


class ChatConfigTests(unittest.TestCase):
    def test_original_defaults_and_private_key(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            Path(temp, '.env').write_text('DEEPSEEK_API_KEY=synthetic-secret\nDEEPSEEK_BASE_URL=https://api.deepseek.com\n', encoding='utf-8')
            config = ModelConfig.from_project(temp)
            config.validate()
            self.assertEqual(config.provider, 'deepseek')
            self.assertEqual(config.model, 'deepseek-v4-flash')
            self.assertNotIn('synthetic-secret', repr(config))

    def test_local_file_over_parent_and_environment_over_file(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            parent = Path(temp)
            child = parent / 'app'
            child.mkdir()
            (parent / '.env').write_text('CHAT_MODEL=parent-model\nDEEPSEEK_API_KEY=parent-key\n', encoding='utf-8')
            (child / '.env').write_text('CHAT_MODEL=child-model\n', encoding='utf-8')
            self.assertEqual(ModelConfig.from_project(child).model, 'child-model')
            self.assertEqual(ModelConfig.from_project(child).api_key, 'parent-key')
            with patch.dict(os.environ, {'CHAT_MODEL':'environment-model'}):
                self.assertEqual(ModelConfig.from_project(child).model, 'environment-model')

    def test_no_embedding_key_fallback_for_deepseek(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {}, clear=True):
            Path(temp, '.env').write_text('OPENAI_API_KEY=embedding-key\n', encoding='utf-8')
            config = ModelConfig.from_project(temp)
            self.assertFalse(config.api_key)
            with self.assertRaises(ValueError):
                config.validate()


if __name__ == '__main__':
    unittest.main()
