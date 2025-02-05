from agent.tools import YouTubeTranscriptTool
from crewai import Agent, Task, Crew, Process
import os

os.environ['CREWAI_TRACKING'] = 'false'

class YTSummaryCrew:
    def __init__(self, youtube_url:str):
        self.youtube_url = youtube_url
        self.transcript_tool = YouTubeTranscriptTool()
    def run(self):
        # Define agents
        researcher = Agent(
            role='YouTube Researcher',
            goal='Extract and analyze video content',
            backstory='Expert in understanding and processing video content',
            tools=[self.transcript_tool],
            verbose=True
            # allow_delegation=False,
        )

        summarizer = Agent(
            role='Professional Summarizer',
            goal='Create concise and informative summaries',
            backstory='Expert in distilling complex information into key points',
            verbose=True
            # allow_delegation=False,
        )

        # Define tasks
        transcript_task = Task(
            description=f'Extract transcript from {self.youtube_url}',
            agent=researcher,
            expected_output='Full video transcript in text format with proper frontend formatting',
        )

        summary_task = Task(
            description='Create comprehensive summary',
            agent=summarizer,
            expected_output='Bullet-point summary with key points and main conclusions',
            context=[transcript_task]
        )

        # Create and run crew
        crew = Crew(
            agents=[researcher, summarizer],
            tasks=[transcript_task, summary_task],
            process=Process.sequential,
            verbose=True
        )

        return crew.kickoff()