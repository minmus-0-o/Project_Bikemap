import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from database import Base, User  # Импортируем базу и модель пользователя
from main import app, get_db

# 1. Настройка тестовой базы данных в оперативной памяти
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, StaticPool
from sqlalchemy.orm import sessionmaker
from database import Base
from main import app, get_db

# 1. Используем StaticPool, чтобы соединение с БД в памяти не закрывалось между запросами
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool, # КРИТИЧНО для SQLite в памяти
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 2. Переопределяем БД
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

# 3. Обновленная фикстура
@pytest.fixture(autouse=True, scope="module") # Создаем таблицы один раз на весь модуль
def setup_database():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

# --- САМИ ТЕСТЫ ---

def test_register_user():
    """Проверка успешной регистрации пользователя"""
    response = client.post(
        "/register", 
        data={"username": "testrider", "password": "securepass"}
    )
    # Если после регистрации у тебя редирект (303), проверяем его
    # Если просто JSON с успехом, то 200
    assert response.status_code in [200, 303]

def test_login_user():
    """Проверка входа в аккаунт"""
    # Сначала регистрируем
    client.post("/register", data={"username": "gleb", "password": "123"})
    
    # Пытаемся войти
    response = client.post(
        "/login", 
        data={"username": "gleb", "password": "123"},
        follow_redirects=False # Чтобы увидеть статус редиректа, а не конечную страницу
    )
    # Обычно после логина идет редирект на главную (303 See Other)
    assert response.status_code == 303

def test_login_wrong_password():
    """Проверка входа с неправильным паролем"""
    # Используем другое имя, чтобы не было конфликта с предыдущим тестом
    client.post("/register", data={"username": "gleb_unique", "password": "123"})
    
    response = client.post(
        "/login", 
        data={"username": "gleb_unique", "password": "wrongpassword"}
    )
    # Проверяем, что нас НЕ пустило (статус не 303 или мы остались на странице логина)
    assert response.status_code != 303