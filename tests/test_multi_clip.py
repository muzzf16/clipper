import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock dependencies before importing ViralClipGenerator
sys.modules['yt_dlp'] = MagicMock()
sys.modules['ffmpeg'] = MagicMock()
sys.modules['googleapiclient'] = MagicMock()
sys.modules['googleapiclient.discovery'] = MagicMock()
sys.modules['googleapiclient.http'] = MagicMock()
sys.modules['google.auth.transport.requests'] = MagicMock()
sys.modules['google.oauth2.credentials'] = MagicMock()
sys.modules['google_auth_oauthlib.flow'] = MagicMock()
sys.modules['whisper'] = MagicMock()
sys.modules['torch'] = MagicMock()
sys.modules['cv2'] = MagicMock()
sys.modules['numpy'] = MagicMock()

from src.core.viral_clipper_complete import ViralClipGenerator

class TestMultiClipGeneration(unittest.TestCase):
    def setUp(self):
        self.generator = ViralClipGenerator()
        # Mock external dependencies
        self.generator.download_video = MagicMock(return_value=("test_video.mp4", "Test Video", "test_id"))
        self.generator.content_analyzer = MagicMock()
        self.generator.detect_speakers_from_segment = MagicMock(return_value=[])
        self.generator.create_smart_single_speaker_clip = MagicMock(return_value=True)
        self.generator.transcribe_audio = MagicMock(return_value=("test.srt", []))
        self.generator.burn_captions = MagicMock(return_value="test_burned.mp4")
        
        # Mock os.path.getsize and os.path.exists and os.remove
        self.patcher_exists = patch('os.path.exists', return_value=True)
        self.patcher_getsize = patch('os.path.getsize', return_value=1024*1024)
        self.patcher_remove = patch('os.remove')
        self.mock_exists = self.patcher_exists.start()
        self.mock_getsize = self.patcher_getsize.start()
        self.mock_remove = self.patcher_remove.start()

    def tearDown(self):
        self.patcher_exists.stop()
        self.patcher_getsize.stop()
        self.patcher_remove.stop()

    @patch('src.core.viral_clipper_complete.ffmpeg')
    @patch('src.core.viral_clipper_complete.whisper')
    def test_generate_multiple_clips(self, mock_whisper, mock_ffmpeg):
        # Setup mocks
        mock_model = MagicMock()
        mock_model.transcribe.return_value = {'text': "Test transcript"}
        mock_whisper.load_model.return_value = mock_model
        
        # Mock AI response for 2 clips
        self.generator.content_analyzer.analyze_transcript.return_value = [
            {
                'start_time': 10,
                'end_time': 40,
                'title': 'Clip 1',
                'reason': 'Funny',
                'score': 9
            },
            {
                'start_time': 60,
                'end_time': 90,
                'title': 'Clip 2',
                'reason': 'Engaging',
                'score': 8
            }
        ]
        
        # Run generation
        clips = self.generator.generate_multiple_viral_clips("http://test.com", num_clips=2)
        
        # Verify results
        self.assertEqual(len(clips), 2)
        self.assertEqual(clips[0]['start_time'], 10)
        self.assertEqual(clips[1]['start_time'], 60)
        
        # Verify AI was called with num_clips=2
        self.generator.content_analyzer.analyze_transcript.assert_called_with("Test transcript", num_clips=2)

if __name__ == '__main__':
    unittest.main()
