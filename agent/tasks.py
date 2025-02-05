# agent/tasks.py

import os
import json
from celery import Celery
from pymongo import MongoClient
from crew import YTSummaryCrew  # from your existing crew.py
from bson import ObjectId

# Read broker and backend from environment, or fallback to local defaults
# CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
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

@celery_app.task
def process_video_task(user_id: str, youtube_url: str) -> str:
    """
    This Celery task runs the YTSummaryCrew to process the requested video
    and then stores the result in MongoDB. Returns the created blog _id as a string.
    """
    try:
        summary_crew = YTSummaryCrew(youtube_url)
        result = summary_crew.run()

        # Convert the summary result to JSON string for safer storage
        result_json_str = json.dumps(result, default=str)
        
        # Generate YouTube thumbnail URL
        video_id = youtube_url.split("v=")[1]
        thumbnail_url = f"http://img.youtube.com/vi/{video_id}/0.jpg"

        # Insert into Mongo
        blog_post = {
            "user_id": user_id,
            "youtube_url": youtube_url,
            "content": result_json_str,       # store JSON or just the raw string
            "thumbnail": thumbnail_url,
        }
        inserted = blogs_collection.insert_one(blog_post)
        return str(inserted.inserted_id)  # Return the ObjectId as a string

    except Exception as e:
        # Celery will store the exception's string in the task result if it fails
        return f"Error in process_video_task: {str(e)}"
