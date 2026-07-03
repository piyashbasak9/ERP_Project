from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from .db import Base

class Permission(Base):
    __tablename__ = 'sa_permissions'
    
    id = Column(Integer, primary_key=True, index=True)
    url_pattern = Column(String(255), unique=True, index=True, nullable=False)
    is_allowed = Column(Boolean, default=True, nullable=False)
    description = Column(String(100), nullable=True)



class Role(Base):
    __tablename__ = 'sa_roles'
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), unique=True, index=True, nullable=False)
    permissions = relationship(
        "Permission",
        secondary="sa_role_permissions",
        lazy="selectin"
    )



class RolePermission(Base):
    __tablename__ = 'sa_role_permissions'
    
    role_id = Column(Integer, ForeignKey('sa_roles.id', ondelete='CASCADE'), primary_key=True)
    permission_id = Column(Integer, ForeignKey('sa_permissions.id', ondelete='CASCADE'), primary_key=True)



class UserRole(Base):
    __tablename__ = 'sa_user_roles'
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, unique=True, index=True, nullable=False) 
    role_id = Column(Integer, ForeignKey('sa_roles.id', ondelete='CASCADE'), nullable=False)
    
    role = relationship("Role", lazy="joined")