import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Add src to path
# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.core.content_analyzer import ViralContentAnalyzer

class TestGeminiSystemPrompt(unittest.TestCase):
    @patch('src.core.content_analyzer.genai')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test_key'})
    def test_default_system_prompt(self, mock_genai):
        # Setup mock
        mock_model_class = mock_genai.GenerativeModel
        
        # Initialize analyzer without custom prompt
        analyzer = ViralContentAnalyzer()
        
        # Verify GenerativeModel was called with default system instruction
        mock_model_class.assert_called_once()
        call_kwargs = mock_model_class.call_args[1]
        self.assertIn('system_instruction', call_kwargs)
        self.assertIn('viral content expert', call_kwargs['system_instruction'])

    @patch('src.core.content_analyzer.genai')
    @patch.dict(os.environ, {'GEMINI_API_KEY': 'test_key'})
    def test_custom_system_prompt(self, mock_genai):
        # Setup mock
        mock_model_class = mock_genai.GenerativeModel
        
        # Custom prompt
        custom_prompt = "You are a potato."
        
        # Initialize analyzer with custom prompt
        analyzer = ViralContentAnalyzer(system_instruction=custom_prompt)
        
        # Verify GenerativeModel was called with custom system instruction
        mock_model_class.assert_called_once()
        call_kwargs = mock_model_class.call_args[1]
        self.assertEqual(call_kwargs['system_instruction'], custom_prompt)

if __name__ == '__main__':
    unittest.main()
