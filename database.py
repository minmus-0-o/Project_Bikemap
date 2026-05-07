from sqlalchemy import Boolean, create_engine, Column, Integer, String, Date, ForeignKey, Float
from sqlalchemy.orm import sessionmaker, declarative_base

URL_DATABASE = "sqlite:///.velo_tour.db"

engine = create_engine(URL_DATABASE, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    avatar_url = Column(String, nullable=True)
    is_community = Column(Boolean, default=False)

class Ride(Base):
    __tablename__ = "rides"
    
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(String, nullable=True)
    ride_date = Column(Date)
    gpx_file = Column(String)
    start_lat = Column(Float)      # ← исправил с Integer на Float
    start_lon = Column(Float)      # ← исправил
    length = Column(Float, nullable=True)   # ← НОВОЕ ПОЛЕ (в метрах)
    
    user_id = Column(Integer, ForeignKey("users.id"))