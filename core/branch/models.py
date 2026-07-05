from django.db import models
from sqlalchemy import Column, Integer, String, ForeignKey

# Create your models here.


class Branch(models.Model):
    __tablename__ = 'branches'

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True, nullable=False)
    code = Column(String(10), unique=True, index=True, nullable=False)
    address_id = Column(Integer, ForeignKey('addresses.id', ondelete='SET NULL'), nullable=True)
    is_active = Column(Integer, default=1, nullable=False)
    created_by = Column(Integer, nullable=False)
    updated_by = Column(Integer, nullable=False)
    created_at = Column(String(50), nullable=False)
    updated_at = Column(String(50), nullable=False)





