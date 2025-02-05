from crewai.tools import BaseTool
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import NoTranscriptFound
from urllib.parse import urlparse, parse_qs

class YouTubeTranscriptTool(BaseTool):
    name: str = "YouTube Transcript Extractor"
    description: str = "Extracts transcript from YouTube videos in multiple languages"

    def _run(self, youtube_url: str) -> str:
        try:
            video_id = self.extract_video_id(youtube_url)
            return self.get_best_transcript(video_id)
        except Exception as e:
            return f"Error: {str(e)}"

    def get_best_transcript(self, video_id: str) -> str:
        try:
            # Try English first
            transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'])
            return " ".join([entry['text'] for entry in transcript])
        except NoTranscriptFound:
            try:
                # Get available transcripts
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                
                # Try Hindi
                try:
                    transcript = transcript_list.find_transcript(['hi'])
                    return " ".join([entry['text'] for entry in transcript.fetch()])
                except:
                    # Get any available and translate to English
                    transcript = transcript_list.find_manually_created_transcript()
                    translated = transcript.translate('en').fetch()
                    return " ".join([entry['text'] for entry in translated])
            except Exception as e:
                return f"Error: No suitable transcript found. {str(e)}"

    def extract_video_id(self, url: str):
        query = urlparse(url)
        if query.hostname == 'youtu.be':
            return query.path[1:]
        if query.hostname in ('www.youtube.com', 'youtube.com'):
            if query.path == '/watch':
                return parse_qs(query.query)['v'][0]
            if query.path.startswith('/embed/'):
                return query.path.split('/')[2]
            if query.path.startswith('/v/'):
                return query.path.split('/')[2]
        return None