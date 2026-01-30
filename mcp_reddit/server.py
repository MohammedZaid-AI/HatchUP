from mcp.server import FastMCP
import praw
import os
from dotenv import load_dotenv
from pathlib import Path
import sys


# Load .env from the same directory as this script
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)

mcp=FastMCP("Reddit")

@mcp.tool()
def fetch_reddit_posts_with_comments(subreddit="all", limit="5", comments_per_post="15"):
    """
    Fetch hot posts and top comments from a subreddit.
    """
    try:
        # Lazy initialization
        client_id = os.getenv("REDDIT_CLIENT_ID")
        client_secret = os.getenv("REDDIT_CLIENT_SECRET")
        
        if not client_id or not client_secret:
            return {"error": "Reddit API credentials (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET) are missing.", "posts": []}

        reddit_client = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=os.getenv("USER_AGENT", "echolab-mcp-reddit/0.1")
        )

        # Convert string inputs to int
        limit = int(limit)
        comments_per_post = int(comments_per_post)

        posts_data = []
        sub = reddit_client.subreddit(subreddit)
        submissions = sub.hot(limit=limit)

        for post in submissions:
            post_info = {
                "id": post.id,
                "title": post.title,
                "author": str(post.author) if post.author else "deleted",
                "url": f"https://reddit.com{post.permalink}",
                "score": int(post.score),
                "num_comments": int(post.num_comments),
                "created_utc": float(post.created_utc),
                "comments": []
            }

            post.comments.replace_more(limit=0)
            for comment in post.comments[:comments_per_post]:
                post_info["comments"].append({
                    "author": str(comment.author) if comment.author else "deleted",
                    "body": comment.body or "",
                    "score": int(comment.score)
                })

            posts_data.append(post_info)

        # Always return something structured
        return {"posts": posts_data}

    except Exception as e:
        return {"error": str(e), "posts": []}



if __name__ == "__main__":
    print("Reddit MCP Server is running...", file=sys.stderr)
    mcp.run(transport="stdio")