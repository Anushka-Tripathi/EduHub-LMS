"""Development server:  python run.py"""
import os

from app import app

if __name__ == "__main__":
    app.run(host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "5000")), debug=os.getenv("APP_ENV") != "production")
