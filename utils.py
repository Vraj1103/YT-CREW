from http.client import HTTPException
from pydantic import BaseModel,EmailStr
import os
from pymongo import MongoClient
from crew import YTSummaryCrew
from datetime import datetime
from bson import ObjectId
from typing import Optional
import json
from openai import OpenAI
# from agent.tasks import pinecone_index
from agent.tasks import get_embedding
from pinecone import Pinecone, ServerlessSpec

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "youtube-summaries")
PINECONE_CLOUD = os.getenv("PINECONE_CLOUD", "aws")
PINECONE_REGION = os.getenv("PINECONE_REGION", "us-east-1")

pc = Pinecone(api_key=PINECONE_API_KEY)
existing_indexes = pc.list_indexes().names()

# Create the index if it doesn't exist
# if PINECONE_INDEX_NAME not in existing_indexes:
#     pc.create_index(
#         name=PINECONE_INDEX_NAME,
#         dimension=1536,  # for text-embedding-ada-002
#         metric="cosine", # or "euclidean" / "dotproduct"
#         spec=ServerlessSpec(
#             cloud=PINECONE_CLOUD,
#             region=PINECONE_REGION
#         )
#     )

# Connect to the index
pinecone_index = pc.Index(PINECONE_INDEX_NAME)



MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "yt-crew")
client = MongoClient(MONGO_URI)

db = client[DB_NAME]

# Define collections (for example, 'users' and 'blogs')
users_collection = db["users"]
blogs_collection = db["blogs"]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)


def get_blog_by_user_and_title(user_id: str, video_title: str) -> dict:
    """
    Fetch the blog document based on user_id and video_title from MongoDB.
    (This is used to know which video to process and to obtain its identifiers.)
    """
    blog = blogs_collection.find_one({
        "user_id": user_id,
        "video_title": video_title
    })
    if blog:
        blog["_id"] = str(blog["_id"])

    # print(f"get_blog_by_user_and_title: {blog}")
    return blog

def fetch_summary_text(user_id: str, youtube_url: str) -> str:
    """
    Query Pinecone for the summary vector using a zero-vector query and filter by type "summary".
    Returns the stored summary_text from the metadata.
    """
    dummy_vector = [0.0] * 1536  # 1536 dimensions for text-embedding-ada-002
    filter_conditions = {
        "user_id": user_id,
        "youtube_url": youtube_url,
        "type": "summary"
    }
    print(f"fetch_summary_text: {filter_conditions}")
    response = pinecone_index.query(
        vector=dummy_vector,
        top_k=1,
        filter=filter_conditions,
        include_metadata=True
    )
    print(f"fetch_summary_text response: {response}")
    matches = response.get("matches", [])
    if matches:
        meta = matches[0].get("metadata", {})
        return meta.get("summary_text")
    return None


def fetch_relevant_transcript_chunks(user_id: str, youtube_url: str, query_text: str, top_k: int = 5) -> list:
    """
    Embed the user's query and perform a similarity search in Pinecone for transcript_chunk vectors.
    Returns a list of chunk_text values from the top matches.
    """
    query_embedding = get_embedding(query_text)
    filter_conditions = {
        "user_id": user_id,
        "youtube_url": youtube_url,
        "type": "transcript_chunk"
    }
    response = pinecone_index.query(
        vector=query_embedding,
        top_k=top_k,
        filter=filter_conditions,
        include_metadata=True
    )
    chunks = []
    for match in response.get("matches", []):
        meta = match.get("metadata", {})
        chunk_text = meta.get("chunk_text")
        if chunk_text:
            chunks.append(chunk_text)
    return chunks

def build_answer_prompt(query: str, summary_text: str, transcript_chunks: list) -> str:
    """
    Construct a prompt for OpenAI using the summary and transcript chunk excerpts as context,
    along with the user's question.
    """
    context = "\n\n".join(transcript_chunks)
    prompt = f"""
    You are a knowledgeable assistant. Using the following context from a YouTube video, answer the question clearly and concisely.

    Comprehensive Summary:
    {summary_text}

    Transcript Excerpts:
    {context}

    Question: {query}

    Provide your answer below:
    """
    return prompt.strip()

def call_openai_for_answer(prompt: str) -> str:
    """
    Call OpenAI's chat API (GPT-3.5-turbo) with the given prompt and return the answer text.
    """
    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an expert answer generator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=1024,
        )
        answer = response.choices[0].message.content
        return answer.strip()
    except Exception as e:
        print(f"Error calling OpenAI for answer: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error generating answer from OpenAI.")

# def call_openai_for_answer(prompt: str) -> str:
#     """
#     Call OpenAI's chat (o1-preview) with the given prompt and return the answer text.
#     """
#     try:
#         response = openai_client.chat.completions.create(
#             model="o1-preview",
#             messages=[
#                 {
#                     "role": "user",
#                     "content": "You are an expert answer generator. " 
#                                "Please provide a concise answer to the following:\n\n"
#                                f"{prompt}"
#                 }
#             ],
#             # temperature=0.7,
#             max_completion_tokens=1024,
#         )
#         answer = response.choices[0].message.content
#         return answer.strip()
#     except Exception as e:
#         print(f"Error calling OpenAI for answer: {e}")
#         raise HTTPException(status_code=500, detail="Error generating answer from OpenAI.")