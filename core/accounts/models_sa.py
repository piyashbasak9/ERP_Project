from sqlalchemy import Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from ERP.db import Base

class Permission(Base):
    __tablename__ = 'sa_permissions'
    
    id = Column(Integer, primary_key=True, index=True)
    url_pattern = Column(String(255), unique=True, index=True, nullable=False)
    route_name = Column(String(255), unique=True, index=True, nullable=True)
    is_allowed = Column(Boolean, default=True, nullable=False)
    description = Column(String(100), nullable=True)

    def __init__(self, *args, **kwargs):
        route_name = kwargs.get('route_name')
        url_pattern = kwargs.get('url_pattern')
        if route_name and not url_pattern:
            kwargs['url_pattern'] = route_name
        super().__init__(*args, **kwargs)


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

    @property
    def role_name(self):
        return self.role.name if self.role else None
