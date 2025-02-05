# from crewai import Agent
# from .tools import yt_tool

# from dotenv import load_dotenv
# import os

# load_dotenv()

# # Set OpenAI API configurations from environment variables
# os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")
# os.environ["OPENAI_MODEL_NAME"] = "gpt-4-0125-preview"

# ## Create a senior blog content researcher
# blog_researcher = Agent(
#     role='Blog Researcher from YouTube Videos',
#     goal='Get the relevant video transcription for the topic {topic} from the provided YouTube channel',
#     verbose=True,           # Fixed typo from 'verboe' to 'verbose'
#     memory=True,
#     backstory=(
#         "Expert in understanding videos in AI, Data Science, Machine Learning, "
#         "and Gen AI while providing actionable suggestions."
#     ),
#     tools=[yt_tool],
#     allow_delegation=True
# )

# ## Create a senior blog writer agent with the YouTube tool
# blog_writer = Agent(
#     role='Blog Writer',
#     goal='Narrate compelling tech stories about the video {topic} from YouTube videos',
#     verbose=True,
#     memory=True,
#     backstory=(
#         "With a flair for simplifying complex topics, you craft engaging narratives that captivate "
#         "and educate, bringing new discoveries to light in an accessible manner."
#     ),
#     tools=[yt_tool],
#     allow_delegation=False
# )
