from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker
from django.conf import settings

DATABASE_URL = getattr(settings, 'SQLALCHEMY_DATABASE_URL', None)
if not DATABASE_URL:
    raise ValueError("SQLALCHEMY_DATABASE_URL is not set in Django settings.")

engine = create_engine(DATABASE_URL, pool_size=10, echo=False)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()