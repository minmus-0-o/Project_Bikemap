from fastapi import FastAPI, Request, Form, Depends, Cookie, Response, UploadFile, File 
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import shutil
import os
import gpxpy
from datetime import datetime

import database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")

database.Base.metadata.create_all(bind=database.engine)

templates = Jinja2Templates(directory="templates")

def get_gpx_start_point(file_path):
    with open(file_path, 'r') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
        if gpx.tracks:
            first_track = gpx.tracks[0]
            if first_track.segments:
                first_segment = first_track.segments[0]
                if first_segment.points:
                    first_point = first_segment.points[0]
                    return first_point.latitude, first_point.longitude
    return None, None

def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, user_id: str = Cookie(None), db: Session = Depends(get_db)):
    user = None
    if user_id:
        user = db.query(database.User).filter(database.User.id == int(user_id)).first()

    return templates.TemplateResponse(
    request=request,    
    name="index.html", 
    context={"user": user}
)

@app.get("/register", response_class=HTMLResponse)
def get_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")

@app.post("/register")
def register_user(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    hashed_password = pwd_context.hash(password)
    new_user = database.User(username=username, hashed_password=hashed_password)

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    res = RedirectResponse(url="/", status_code=303)
    res.set_cookie(key="user_id", value=str(new_user.id))
    return res

@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/login")
def login_user(
    username: str = Form(...), 
    password: str = Form(...), 
    db: Session = Depends(get_db)
):
    user = db.query(database.User).filter(database.User.username == username).first()

    if not user or not pwd_context.verify(password, user.hashed_password):
        return "Неверные данные"
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="user_id", value=str(user.id))
    return response

@app.get("/logout", response_class=HTMLResponse)
def get_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_id")
    return response

if not os.path.exists("uploads"):
    os.makedirs("uploads")

@app.post("/upload_gpx")
async def upload_gpx(
    title: str = Form(...),
    description: str = Form(None),
    ride_date: str = Form(...),
    gpx_file: UploadFile = File(...), # Имя переменной должно быть gpx_file
    user_id: str = Cookie(None),
    db: Session = Depends(get_db)
):
    if not user_id:
        return "Ошибка: Вы должны быть авторизованы"

    file_path = f"uploads/{gpx_file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(gpx_file.file, buffer)
    
    lat, lon = get_gpx_start_point(file_path)
    
    if lat is None:
        return "Ошибка: Не удалось найти координаты в GPX файле"

    date_obj = datetime.strptime(ride_date, "%Y-%m-%d").date()
    
    new_ride = database.Ride(
        title=title,
        ride_date=date_obj,
        description=description,
        gpx_file=file_path,
        start_lat=lat,
        start_lon=lon,
        user_id=int(user_id)
    )
    
    db.add(new_ride)
    db.commit()
    
    return RedirectResponse(url="/", status_code=303)

@app.get("/get_rides")
def get_rides(date: str, db: Session = Depends(get_db)):

    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    
    rides = db.query(database.Ride).filter(database.Ride.ride_date == target_date).all()

    return [
        {
            "id": r.id,
            "title": r.title,
            "description": r.description or "",
            "lat": r.start_lat,
            "lon": r.start_lon,
            "gpx_path": r.gpx_file
        } for r in rides
    ]

@app.get("/get_user_info")
def get_user_info(user_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not user_id:
        return {"error": "Not authorized"}
    
    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if user:
        return {
            "username": user.username,
            # Вместо user.is_community используй getattr
            "role": "Велосообщество" if getattr(user, 'is_community', False) else "Райдер",
            "avatar": user.avatar_url or "https://api.dicebear.com/7.x/avataaars/svg?seed=" + user.username
        }
    return {"error": "User not found"}