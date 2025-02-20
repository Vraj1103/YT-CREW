import os
import json
import logging
import requests
import re
from bs4 import BeautifulSoup

from celery import Celery
from pymongo import MongoClient
from bson import ObjectId

from pinecone import Pinecone, ServerlessSpec
from openai import OpenAI

from crew import YTSummaryCrew


logger = logging.getLogger(__name__)

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
celery_app.conf.broker_connection_retry_on_startup = True

# Connect to your MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "yt-crew")

# client = MongoClient(MONGO_URI)
# db = client[DB_NAME]
# blogs_collection = db["blogs"]

def get_blogs_collection():
    """
    Creates a new MongoClient instance and returns the "blogs" collection.
    Called at task runtime to avoid fork-safety issues.
    """
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    return db["blogs"]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(
  api_key=os.environ['OPENAI_API_KEY'],
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
    text = text.strip()
    # Validate input: make sure text is not empty or just whitespace.
    if not text:
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

def chunk_text_by_words(text: str, chunk_size: int = 500) -> list:
    """
    Splits `text` into chunks of roughly `chunk_size` words.
    Skips empty/duplicate chunks.
    """
    words = text.split()
    chunks = []
    current_chunk_words = []

    for word in words:
        current_chunk_words.append(word)
        # If we've hit the chunk_size limit, finalize this chunk
        if len(current_chunk_words) >= chunk_size:
            chunk_str = " ".join(current_chunk_words).strip()
            chunks.append(chunk_str)
            current_chunk_words = []

    # Handle any leftover words
    if current_chunk_words:
        chunk_str = " ".join(current_chunk_words).strip()
        if chunk_str:
            chunks.append(chunk_str)

    # Remove duplicates and empty
    unique_chunks = []
    seen = set()
    for chunk in chunks:
        if chunk not in seen and chunk.strip():
            unique_chunks.append(chunk)
            seen.add(chunk)
    return unique_chunks


@celery_app.task
def process_video_task(user_id: str, youtube_url: str) -> str:
    """
    This Celery task runs the YTSummaryCrew to process the requested video
    and then stores the result in MongoDB. Returns the created blog _id as a string.
    """
    try:
        logger.info(f"Starting process_video_task for user_id={user_id}, url={youtube_url}")

        # 1. Run the Crew to get transcript and summary
        summary_crew = YTSummaryCrew(youtube_url)
        result = summary_crew.run()
        transcript = str(result['transcript'])
        comprehensive_summary = str(result['summary'])
        # qna_summary = str(result['qna_summary'])

        transcript_json_str = json.dumps(transcript)
        comprehensive_summary_json_str = json.dumps(comprehensive_summary)
        # qna_summary_json_str = json.dumps(qna_summary)

        # Convert the summary result to JSON string for safer storage
        # result_json_str = json.dumps(result, default=str)
        # print("result",result_json_str)
        
        # 2. Get YouTube title + thumbnail
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
            video_title = "Title not found."
            print("Failed to retrieve the video page.")
        
        #  3. Chunk the transcript to avoid huge inputs for embedding
        transcript_chunks = chunk_text_by_words(transcript, chunk_size=500)

        # 4. Insert everything into MongoDB
        blogs_collection = get_blogs_collection()
        blog_post = {
            "user_id": user_id,
            "video_title": video_title,
            "youtube_url": youtube_url,
            "transcript": transcript_json_str,
            "comprehensive_summary": comprehensive_summary_json_str,
            # "qna_summary": qna_summary_json_str,
            "thumbnail": thumbnail_url,
        }
        inserted = blogs_collection.insert_one(blog_post)
        blog_id = str(inserted.inserted_id)
        
        # 5. Embed and upsert the comprehensive summary into Pinecone
        if not comprehensive_summary or not comprehensive_summary.strip():
            raise ValueError("Comprehensive summary is empty. Cannot generate embedding.")
        
        summary_embedding_vector = get_embedding(comprehensive_summary)
        try:
            pinecone_index.upsert(vectors=[
                (
                    blog_id, # Use the blog_id as the Pinecone ID
                    summary_embedding_vector,
                    {
                        "user_id": user_id,
                        "youtube_url": youtube_url,
                        "video_title": video_title,
                        "type": "summary",
                        "summary_text": comprehensive_summary
                    }
                )
            ])
        except Exception as e:
            logger.error(f"Error in upserting to Pinecone: {str(e)}")

        
        # 6. Embed each transcript chunk separately and upsert into Pinecone
        for idx, chunk in enumerate(transcript_chunks):
            try:
                embedding_vector = get_embedding(chunk)
                vector_id = f"{blog_id}_{idx}"  # unique ID per chunk
                pinecone_index.upsert(vectors=[
                    (
                        vector_id,
                        embedding_vector,
                        {
                            "user_id": user_id,
                            "youtube_url": youtube_url,
                            "video_title": video_title,
                            "type": "transcript_chunk",
                            "chunk_index": idx,
                            "chunk_text": chunk
                        }
                    )
                ])
            except Exception as e:
                logger.error(f"Error embedding chunk #{idx} for blog_id={blog_id}: {str(e)}")

        logger.info(f"Task complete for blog_id={blog_id}")
        return blog_id

    except Exception as e:
        # Celery will store the exception's string in the task result if it fails
        logger.error(f"Error in process_video_task: {str(e)}", exc_info=True)

        return f"Error in process_video_task: {str(e)}"
