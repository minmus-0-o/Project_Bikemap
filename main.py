from fastapi import FastAPI, Request, Form, Depends, Cookie, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from passlib.context import CryptContext

import database

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

app = FastAPI()

database.Base.metadata.create_all(bind=database.engine)

templates = Jinja2Templates(directory="templates")

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
    new_user = database.User(username=username, password=hashed_password)

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

    if not user or not pwd_context.verify(password, user.password):
        return "Неверные данные"
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(key="user_id", value=str(user.id))
    return response

@app.get("/logout", response_class=HTMLResponse)
def get_logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie("user_id")
    return response