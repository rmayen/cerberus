from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Role, User
from app.security import hash_password


class UserAlreadyExists(Exception):
    pass


def get_by_username(db: Session, username: str) -> User | None:
    return db.execute(select(User).where(User.username == username)).scalar_one_or_none()


def get_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def list_users(db: Session) -> list[User]:
    return list(db.execute(select(User).order_by(User.id)).scalars())


def create_user(db: Session, username: str, password: str, role: Role) -> User:
    if get_by_username(db, username) is not None:
        raise UserAlreadyExists(username)
    user = User(username=username, hashed_password=hash_password(password), role=role)
    db.add(user)
    db.flush()
    return user
