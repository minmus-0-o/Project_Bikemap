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
import gpxpy

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
app.mount("/static", StaticFiles(directory="static"), name="static")

database.Base.metadata.create_all(bind=database.engine)

templates = Jinja2Templates(directory="templates")


def get_gpx_info(file_path):
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


# ====================== ОСНОВНЫЕ РОУТЫ ======================
@app.get("/", response_class=HTMLResponse)
def read_root(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/register", response_class=HTMLResponse)
def get_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")


@app.post("/register")
def register_user(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    account_type: str = Form("user"),
    db: Session = Depends(get_db)
):
    if db.query(database.User).filter(database.User.username == username).first():
        return "Пользователь с таким логином уже существует"

    hashed_password = pwd_context.hash(password)
    
    is_community = False
    community_requested = False
    is_approved = True

    if account_type == "community":
        community_requested = True
        is_approved = False

    new_user = database.User(
        username=username,
        hashed_password=hashed_password,
        is_community=is_community,
        community_requested=community_requested,
        is_approved=is_approved
    )

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


# ====================== АВАТАРКИ ======================
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

    allowed_types = ["image/jpeg", "image/png", "image/webp", "image/gif"]
    if avatar.content_type not in allowed_types:
        return "Ошибка: Разрешены только изображения"

    avatar_dir = "static/avatars"
    os.makedirs(avatar_dir, exist_ok=True)

    # Удаляем старую аватарку
    if user.avatar_url and user.avatar_url.startswith("/static/avatars/"):
        old_path = "." + user.avatar_url
        if os.path.exists(old_path):
            try:
                os.remove(old_path)
            except:
                pass

    file_ext = os.path.splitext(avatar.filename)[1].lower()
    unique_name = f"user_{user_id}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{file_ext}"
    file_path = f"{avatar_dir}/{unique_name}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(avatar.file, buffer)

    user.avatar_url = f"/static/avatars/{unique_name}"
    db.commit()
    print(f"✅ Аватарка обновлена для пользователя {user.username}: {user.avatar_url}")
    
    return RedirectResponse(url="/", status_code=303)


# ====================== ЗАГРУЗКА МАРШРУТОВ ======================
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

    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if not user:
        return "Ошибка: Пользователь не найден"

    if user.community_requested and not user.is_approved:
        return "Ваш аккаунт ещё ожидает подтверждения администратора"

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
def get_rides(date: str, only_community: bool = False, db: Session = Depends(get_db)):
    target_date = datetime.strptime(date, "%Y-%m-%d").date()
    
    query = db.query(database.Ride).filter(database.Ride.ride_date == target_date)
    
    if only_community:
        query = query.join(database.User).filter(
            database.User.is_community == True,
            database.User.is_approved == True
        )
    
    rides = query.all()

    result = []
    for r in rides:
        length_km = round(r.length / 1000, 2) if getattr(r, 'length', None) else None
        author = db.query(database.User).filter(database.User.id == r.user_id).first()
        
        author_avatar = author.avatar_url if author and author.avatar_url else \
                        f"https://api.dicebear.com/7.x/initials/svg?seed={author.username if author else 'user'}&backgroundColor=0f172a&color=ffffff&fontSize=40"

        result.append({
            "id": r.id,
            "title": r.title,
            "description": r.description or "",
            "lat": r.start_lat,
            "lon": r.start_lon,
            "gpx_path": r.gpx_file,
            "length_km": length_km,
            "author_username": author.username if author else "Неизвестно",
            "author_avatar": author_avatar,
            "user_id": r.user_id          # ← обязательно должно быть
        })
    return result


@app.get("/get_user_info")
def get_user_info(user_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not user_id:
        return {"error": "Not authorized"}
    
    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if not user:
        return {"error": "User not found"}

    if user.community_requested and not user.is_approved:
        role = "Ожидает подтверждения"
    elif user.is_community and user.is_approved:
        role = "Велосообщество"
    else:
        role = "Пользователь"

    avatar = user.avatar_url if user.avatar_url else \
             f"https://api.dicebear.com/7.x/initials/svg?seed={user.username}&backgroundColor=0f172a&color=ffffff&fontSize=40"

    return {
        "username": user.username,
        "user_id": user.id,
        "role": role,
        "avatar": avatar
    }


# ====================== АДМИН-ПАНЕЛЬ ======================
@app.get("/admin", response_class=HTMLResponse)
def admin_panel(request: Request, user_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not user_id:
        return RedirectResponse(url="/login", status_code=303)
    
    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if not user or user.username != "admin":
        return HTMLResponse("Доступ запрещён. Только администратор может заходить сюда.", status_code=403)
    
    return templates.TemplateResponse(request=request, name="admin.html")


@app.get("/admin/requests")
def get_requests(db: Session = Depends(get_db), user_id: str = Cookie(None)):
    if not user_id:
        return []
    admin = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if not admin or admin.username != "admin":
        return []
    
    users = db.query(database.User).filter(
        database.User.community_requested == True,
        database.User.is_approved == False
    ).all()
    
    return [{"id": u.id, "username": u.username} for u in users]


@app.post("/admin/approve/{user_id}")
def approve_community(user_id: int, db: Session = Depends(get_db)):
    """Простая версия без строгой проверки cookie"""
    user = db.query(database.User).filter(database.User.id == user_id).first()
    if user:
        user.is_community = True
        user.is_approved = True
        user.community_requested = False
        db.commit()
        db.refresh(user)
        print(f"✅ УСПЕШНО ОДОБРЕНО: {user.username}")
        return {"success": True}
    return {"error": "Пользователь не найден"}


@app.post("/admin/reject/{user_id}")
def reject_community(user_id: int, db: Session = Depends(get_db)):
    user = db.query(database.User).filter(database.User.id == user_id).first()
    if user:
        user.community_requested = False
        user.is_approved = False
        user.is_community = False
        db.commit()
    return {"success": True}

# ====================== УДАЛЕНИЕ МАРШРУТА ======================
@app.post("/delete_ride/{ride_id}")
def delete_ride(ride_id: int, user_id: str = Cookie(None), db: Session = Depends(get_db)):
    if not user_id:
        return {"error": "Не авторизован"}
    
    user = db.query(database.User).filter(database.User.id == int(user_id)).first()
    if not user:
        return {"error": "Пользователь не найден"}
    
    ride = db.query(database.Ride).filter(database.Ride.id == ride_id).first()
    if not ride:
        return {"error": "Маршрут не найден"}
    
    # Проверка прав: автор или админ
    is_admin = (user.username == "admin")
    is_owner = (ride.user_id == int(user_id))
    
    if not (is_admin or is_owner):
        return {"error": "Нет прав на удаление этого маршрута"}
    
    # Удаляем файл GPX
    if os.path.exists(ride.gpx_file):
        try:
            os.remove(ride.gpx_file)
        except:
            pass
    
    db.delete(ride)
    db.commit()
    
    return {"success": True}


if not os.path.exists("uploads"):
    os.makedirs("uploads")
if not os.path.exists("static/avatars"):
    os.makedirs("static/avatars")