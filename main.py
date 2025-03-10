from fastapi import FastAPI,HTTPException,Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel,EmailStr
import os
from pymongo import MongoClient
from crew import YTSummaryCrew
from datetime import datetime
from bson import ObjectId
from typing import Optional
import json
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def root():
    return {"Welcome to the project YT-CREW"}

# Connect to MongoDB
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME = os.getenv("DB_NAME", "yt-crew")
client = MongoClient(MONGO_URI)

db = client[DB_NAME]

# Define collections (for example, 'users' and 'blogs')
users_collection = db["users"]
blogs_collection = db["blogs"]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY)

@app.get("/db-check")
def db_check():
    # Just a quick check by counting documents in your 'users' collection
    count_users = users_collection.count_documents({})
    return {"message": "Connected to MongoDB successfully!", "users_count": count_users}

class User(BaseModel):
    email: EmailStr
    name: str

class UserInDB(User):
    created_at: datetime = datetime.now()

class BlogPost(BaseModel):
    user_id: str
    youtube_url: str
    content: str
    thumbnail: Optional[str] = None
    created_at: datetime = datetime.now()
    task_id: Optional[str] = None

class VideoRequest(BaseModel):
    user_id: str
    youtube_url: str

class QueryRequest(BaseModel):
    user_id: str
    video_title: str
    query: str

@app.post("/users")
async def create_user(user: User):
    if users_collection.find_one({"email": user.email}):
        raise HTTPException(status_code=400, detail="User already exists")
    
    user_dict = UserInDB(**user.dict()).dict()
    result = users_collection.insert_one(user_dict)
    return {"id": str(result.inserted_id), "message": "User created successfully"}

@app.get("/users/{user_id}")
async def get_user(user_id: str):
    try:
        user = users_collection.find_one({"_id": ObjectId(user_id)})
        if user:
            user["_id"] = str(user["_id"])
            return user
        raise HTTPException(status_code=404, detail="User not found")
    except:
        raise HTTPException(status_code=400, detail="Invalid user ID")

from agent.tasks import process_video_task, celery_app
from celery.result import AsyncResult


@app.post("/process-video")
async def process_video(request: VideoRequest):
    try:
        user = users_collection.find_one({"_id": ObjectId(request.user_id)})
        if not user:
            return HTTPException(status_code=404, detail="User not found")

        existing_blog = blogs_collection.find_one({
            "youtube_url": request.youtube_url,
            "user_id": request.user_id
        })

        # extract content from existing blog
        existing_blog_content = existing_blog.get("content") if existing_blog else None
        
        if existing_blog:
            existing_blog["_id"] = str(existing_blog["_id"])
            return {
                "status": "success",
                "blog_id": str(existing_blog["_id"]),
                "content": existing_blog_content
        }
        # summary_crew = YTSummaryCrew(request.youtube_url)
        # result = summary_crew.run()
        # print("result received",result)
        # result_json_str = json.dumps(result, default=str)
        # print("result received",result_json_str)

        # video_id = request.youtube_url.split("v=")[1]
        # thumbnail_url = f"http://img.youtube.com/vi/{video_id}/0.jpg"
        # blog_post = BlogPost(
        #     user_id=request.user_id,
        #     youtube_url=request.youtube_url,
        #     content=str(result),
        #     thumbnail=thumbnail_url
        # )
        
        # inserted = blogs_collection.insert_one(blog_post.dict())
        task = process_video_task.delay(request.user_id, request.youtube_url)

        return {
            "task_id": task.id,
            "status": "processing"
        }

    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
# api for getting all blocks based on userid
@app.get("/blogs/{user_id}")
async def get_blogs(user_id: str):
    blogs = blogs_collection.find({"user_id": user_id})
    blog_list = []
    for blog in blogs:
        blog["_id"] = str(blog["_id"])
        blog_list.append(blog)
    return blog_list

# api for getting a single blog based on blogid
@app.get("/blog/{blog_id}")
async def get_blog(blog_id: str):
    blog = blogs_collection.find_one({"_id": ObjectId(blog_id)})
    if blog:
        blog["_id"] = str(blog["_id"])
        return blog
    raise HTTPException(status_code=404, detail="Blog not found")

@app.get("/task/{task_id}")
async def get_task_status(task_id: str):
    """
    Poll the Celery task by its ID.
    If finished successfully, retrieve the created blog from Mongo and return it.
    """
    task_result = AsyncResult(task_id, app=celery_app)

    if task_result.ready():
        if task_result.successful():
            # The task returns the blog_id as result
            blog_id = task_result.result
            # If it started with 'Error', treat it as a failure
            if blog_id.startswith("Error"):
                return {"status": "failed", "error": blog_id}
            blog = blogs_collection.find_one({"_id": ObjectId(blog_id)})
            if blog:
                blog["_id"] = str(blog["_id"])
                return {
                    "status": "completed",
                    "blog": blog
                }
            # If no blog found, it’s unusual but handle gracefully
            return {"status": "failed", "error": "Blog not found after task"}
        # If not successful, it could be an exception
        return {"status": "failed", "error": str(task_result.result)}

    # Task is still running
    return {"status": "processing"}

from utils import get_blog_by_user_and_title, fetch_summary_text, fetch_relevant_transcript_chunks, build_answer_prompt, call_openai_for_answer

@app.post("/ask")
async def answer_query(request: QueryRequest):
    """
    Answer a user's query by:
      1. Retrieving the corresponding blog (to obtain the YouTube URL).
      2. Querying Pinecone for the stored summary and the most relevant transcript chunks.
      3. Building a prompt and calling OpenAI to generate an answer.
    """
    blog = get_blog_by_user_and_title(request.user_id, request.video_title)
    if not blog:
        raise HTTPException(status_code=404, detail="Blog not found for the given user and video title.")
    print("Blog found")
    
    youtube_url = blog.get("youtube_url")
    if not youtube_url:
        raise HTTPException(status_code=500, detail="Blog is missing the YouTube URL.")
    print(f"Youtube URL found")

    # Fetch summary text from Pinecone (stored in metadata as "summary_text")
    # summary_text = fetch_summary_text(blog.get("user_id"), youtube_url)
    # if not summary_text:
    #     raise HTTPException(status_code=500, detail="Summary vector not found in Pinecone.")
    # print(f"Summary text found")
    
    # Fetch the most relevant transcript chunks using the user's query
    transcript_chunks = fetch_relevant_transcript_chunks(request.user_id, youtube_url, request.query, top_k=5)
    if not transcript_chunks:
        raise HTTPException(status_code=500, detail="Relevant transcript chunks not found in Pinecone.")

    # Build the prompt for the answer
    prompt = build_answer_prompt(request.query, blog.get("comprehensive_summary","No summary provided with this video, use your knowledge"), transcript_chunks)
    print(f"Prompt for answer:\n{prompt}")

    # Call OpenAI to generate the answer
    answer = call_openai_for_answer(prompt)
    return {"answer": answer}
