from fastapi import FastAPI, Request, Form, Depends, Cookie, Response, UploadFile, File 
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from passlib.context import CryptContext
import shutil
import os
from datetime import datetime

import database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")

database.Base.metadata.create_all(bind=database.engine)

templates = Jinja2Templates(directory="templates")

# ====================== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ======================
def get_gpx_info(file_path):
    """Возвращает стартовую точку и длину трека"""
    import gpxpy
    with open(file_path, 'r', encoding='utf-8') as gpx_file:
        gpx = gpxpy.parse(gpx_file)
        
        total_length = 0.0
        if gpx.tracks:
            for track in gpx.tracks:
                total_length += track.length_3d()
        
        lat, lon = None, None
        if gpx.tracks and gpx.tracks[0].segments and gpx.tracks[0].segments[0].points:
            first_point = gpx.tracks[0].segments[0].points[0]
            lat = first_point.latitude
            lon = first_point.longitude
            
    return lat, lon, total_length


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ====================== МАРШРУТЫ ======================
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request, user_id: str = Cookie(None), db: Session = Depends(get_db)):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/register", response_class=HTMLResponse)
def get_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@app.post("/register")
def register_user(response: Response, username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
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
def login_user(username: str = Form(...), password: str = Form(...), db: Session = Depends(get_db)):
    user = db.query(database.User).filter(database.User.username == username).first()
    if not user or not pwd_context.verify(password, user.hashed_password):
        return "Неверные данные"
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="user_id", value=str(user.id))
    return response


@app.post("/upload_avatar")
async def upload_avatar(
    avatar: UploadFile = File(...),
    user_id: str = Cookie(None),
    db: Session = Depends(get_db)
):
    if not user_id:
        return RedirectResponse(url="/", status_code=303)

    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if not user:
        return RedirectResponse(url="/", status_code=303)

    # Проверка типа файла
    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if avatar.content_type not in allowed_types:
        return "Ошибка: Разрешены только изображения (jpg, png, webp, gif)"

    avatar_dir = "static/avatars"
    os.makedirs(avatar_dir, exist_ok=True)

    # Удаление старой аватарки
    if user.avatar_url and user.avatar_url.startswith("/static/avatars/"):
        old_file_path = "." + user.avatar_url  # добавляем точку в начало
        if os.path.exists(old_file_path):
            try:
                os.remove(old_file_path)
                print(f"Старая аватарка удалена: {old_file_path}")
            except Exception as e:
                print(f"Не удалось удалить старую аватарку: {e}")

    # Сохранение новой
    file_ext = os.path.splitext(avatar.filename)[1].lower()
    unique_name = f"user_{user_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{file_ext}"
    file_path = f"{avatar_dir}/{unique_name}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(avatar.file, buffer)

    user.avatar_url = f"/static/avatars/{unique_name}"
    db.commit()

    return RedirectResponse(url="/", status_code=303)


@app.post("/upload_gpx")
async def upload_gpx(
    title: str = Form(...),
    description: str = Form(None),
    ride_date: str = Form(...),
    gpx_file: UploadFile = File(...),
    user_id: str = Cookie(None),
    db: Session = Depends(get_db)
):
    if not user_id:
        return "Ошибка: Вы должны быть авторизованы"

    # Сохранение файла
    file_ext = os.path.splitext(gpx_file.filename)[1].lower()
    unique_filename = f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{os.urandom(8).hex()}{file_ext}"
    file_path = f"uploads/{unique_filename}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(gpx_file.file, buffer)
    
    lat, lon, length = get_gpx_info(file_path)
    
    if lat is None:
        return "Ошибка: Не удалось обработать GPX файл"

    date_obj = datetime.strptime(ride_date, "%Y-%m-%d").date()
    
    new_ride = database.Ride(
        title=title,
        ride_date=date_obj,
        description=description,
        gpx_file=file_path,
        start_lat=lat,
        start_lon=lon,
        length=length,
        user_id=int(user_id)
    )
    
    db.add(new_ride)
    db.commit()
    
    return RedirectResponse(url="/", status_code=303)


@app.get("/get_rides")
def get_rides(date: str, db: Session = Depends(get_db)):
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    rides = db.query(database.Ride).filter(database.Ride.ride_date == target_date).all()

    result = []
    for r in rides:
        length_km = round(r.length / 1000, 2) if r.length else None
        result.append({
            "id": r.id,
            "title": r.title,
            "description": r.description or "",
            "lat": r.start_lat,
            "lon": r.start_lon,
            "gpx_path": r.gpx_file,
            "length_km": length_km
        })
    return result


@app.get("/get_user_info")
def get_user_info(user_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not user_id:
        return {"error": "Not authorized"}
    
    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if user:
        return {
            "username": user.username,
            "role": "Велосообщество" if getattr(user, 'is_community', False) else "Райдер",
            "avatar": user.avatar_url or f"https://api.dicebear.com/7.x/avataaars/svg?seed={user.username}"
        }
    return {"error": "User not found"}


if not os.path.exists("uploads"):
    os.makedirs("uploads")