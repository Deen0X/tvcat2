import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from scraper.database import Base, User
import bcrypt

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")
os.makedirs(DATA_DIR, exist_ok=True)
db_path = os.path.join(DATA_DIR, "webscrapper_default.db")

if os.path.exists(db_path):
    os.remove(db_path)

engine = create_engine(f"sqlite:///{db_path}", echo=False)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)
session = Session()
try:
    pw = bcrypt.hashpw("admin123".encode(), bcrypt.gensalt()).decode()
    session.add(User(username="admin", password_hash=pw))
    session.commit()
finally:
    session.close()

print(f"OK: {db_path}")
