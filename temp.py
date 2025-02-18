import requests
from bs4 import BeautifulSoup

video_id = "IVbm2a6lVBo"
url = f"https://www.youtube.com/watch?v={video_id}"
response = requests.get(url)

if response.status_code == 200:
    soup = BeautifulSoup(response.text, 'html.parser')
    title_tag = soup.find("meta", {"name": "title"})
    if title_tag and title_tag.get("content"):
        video_title = title_tag["content"]
        print("Video Title:", video_title)
    else:
        print("Title not found.")
else:
    print("Failed to retrieve the video page.")
