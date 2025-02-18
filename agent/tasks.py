# agent/tasks.py

import os
import json
from celery import Celery
from pymongo import MongoClient
from crew import YTSummaryCrew  # from your existing crew.py
from bson import ObjectId
import requests
from bs4 import BeautifulSoup
from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI

# Read broker and backend from environment, or fallback to local defaults

# for localhost:
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")

# CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", CELERY_BROKER_URL)

celery_app = Celery(
    'ytcrew_tasks',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND
)

# Connect to your MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "yt-crew")
client = MongoClient(MONGO_URI)
db = client[DB_NAME]
blogs_collection = db["blogs"]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
# openai.api_key = OPENAI_API_KEY
openai_client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],  # this is also the default, it can be omitted
)
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "youtube-summaries")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

pc = Pinecone(api_key=PINECONE_API_KEY)
existing_indexes = pc.list_indexes().names()

# Create the index if it doesn't exist
if PINECONE_INDEX_NAME not in existing_indexes:
    pc.create_index(
        name=PINECONE_INDEX_NAME,
        dimension=1536,  # for text-embedding-ada-002
        metric="cosine", # or "euclidean" / "dotproduct"
        spec=ServerlessSpec(
            cloud=PINECONE_CLOUD,
            region=PINECONE_REGION
        )
    )

# Connect to the index
pinecone_index = pc.Index(PINECONE_INDEX_NAME)

def get_embedding(text: str) -> list:
    """
    Uses OpenAI's API to generate an embedding vector for the provided text.
    Raises an error if the text is empty or if the returned embedding does not
    match the expected dimension.
    """
    # Ensure text is a string
    if not isinstance(text, str):
        text = str(text)
        
    # Validate input: make sure text is not empty or just whitespace.
    if not text or not text.strip():
        raise ValueError("Input text is empty. Cannot generate embedding.")

    # Generate the embedding with the new API parameter name 'model'
    response = openai_client.embeddings.create(input=[text], model="text-embedding-ada-002")
    
    # Validate response structure
    if not response.data or len(response.data) == 0:
        raise ValueError("No embedding data returned from OpenAI.")

    embedding = response.data[0].embedding

    # Check that the embedding has the expected dimension (1536)
    expected_dimension = 1536
    if not embedding or len(embedding) != expected_dimension:
        raise ValueError(f"Embedding dimension {len(embedding)} does not match the expected dimension {expected_dimension}.")

    return embedding


@celery_app.task
def process_video_task(user_id: str, youtube_url: str) -> str:
    """
    This Celery task runs the YTSummaryCrew to process the requested video
    and then stores the result in MongoDB. Returns the created blog _id as a string.
    """
    try:
        summary_crew = YTSummaryCrew(youtube_url)
        result = summary_crew.run()
        transcript = str(result['transcript'])
        comprehensive_summary = str(result['summary'])
        qna_summary = str(result['qna_summary'])

        transcript_json_str = json.dumps(transcript)
        comprehensive_summary_json_str = json.dumps(comprehensive_summary)
        qna_summary_json_str = json.dumps(qna_summary)

        # Convert the summary result to JSON string for safer storage
        # result_json_str = json.dumps(result, default=str)
        # print("result",result_json_str)
        # Generate YouTube thumbnail URL
        video_id = youtube_url.split("v=")[1]
        thumbnail_url = f"http://img.youtube.com/vi/{video_id}/0.jpg"
        
        # get yt video title
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = requests.get(url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            title_tag = soup.find("meta", {"name": "title"})
            if title_tag and title_tag.get("content"):
                video_title = title_tag["content"]
                print("Video Title:", video_title)
            else:
                video_title = "Title not found."
                print("Title not found.")
        else:
            print("Failed to retrieve the video page.")

        # Insert into Mongo
        blog_post = {
            "user_id": user_id,
            "video_title": video_title,
            "youtube_url": youtube_url,
            "transcript": transcript_json_str,
            "comprehensive_summary": comprehensive_summary_json_str,
            "qna_summary": qna_summary_json_str,
            "thumbnail": thumbnail_url,
        }
        inserted = blogs_collection.insert_one(blog_post)
        blog_id = str(inserted.inserted_id)
        
        if not comprehensive_summary or not comprehensive_summary.strip():
            raise ValueError("Comprehensive summary is empty. Cannot generate embedding.")
        
        embedding_vector = get_embedding(comprehensive_summary)
        try:
            pinecone_index.upsert(vectors=[
                (
                    blog_id,
                    embedding_vector,
                    {
                        "user_id": user_id,
                        "youtube_url": youtube_url,
                        "video_title": video_title
                    }
                )
            ])
        except Exception as e:
            print(f"Error in upserting to Pinecone: {str(e)}")
        return blog_id

    except Exception as e:
        # Celery will store the exception's string in the task result if it fails
        return f"Error in process_video_task: {str(e)}"
