from django import forms
from django.contrib.auth import get_user_model
from .db import SessionLocal
from .models_sa import Role, Permission, RolePermission
from .utils import get_all_urls
from django.contrib import messages

User = get_user_model()


class RoleForm(forms.Form):
    name = forms.CharField(max_length=50, label="Role Name", widget=forms.TextInput(attrs={'class': 'form-control'}))
    url_permissions = forms.MultipleChoiceField(required=False,widget=forms.CheckboxSelectMultiple(attrs={'class': 'url-checkbox-list'}),label="URL Permissions")

    def __init__(self, *args, **kwargs):
        self.role_id = kwargs.pop('role_id', None)
        super().__init__(*args, **kwargs)

        all_urls = get_all_urls()
        choices = [(item['url'], f"{item['name']}") for item in all_urls]
        self.fields['url_permissions'].choices = choices

        if self.role_id:
            session = SessionLocal()
            try:
                role = session.query(Role).filter(Role.id == self.role_id).first()
                if role:
                    allowed_urls = [p.url_pattern for p in role.permissions if p.is_allowed]
                    self.fields['url_permissions'].initial = allowed_urls
            finally:
                session.close()

    def save(self):
        session = SessionLocal()
        try:
            name = self.cleaned_data['name']
            selected_urls = self.cleaned_data['url_permissions']

            # uniqueness check: prevent creating duplicate role names
            existing_by_name = session.query(Role).filter(Role.name == name).first()
            if self.role_id:
                if existing_by_name and existing_by_name.id != self.role_id:
                    raise ValueError("Role with this name already exists.")

            else:
                if existing_by_name:
                    raise ValueError("Role with this name already exists.")

            if self.role_id:
                role = session.query(Role).filter(Role.id == self.role_id).first()
                role.name = name
            else:
                role = Role(name=name)
                session.add(role)
                session.flush()

            session.query(RolePermission).filter(RolePermission.role_id == role.id).delete()

            for url in selected_urls:
                perm = session.query(Permission).filter(Permission.url_pattern == url).first()
                if not perm:
                    perm = Permission(url_pattern=url, is_allowed=True)
                    session.add(perm)
                    session.flush()
                else:
                    perm.is_allowed = True

                role_perm = RolePermission(role_id=role.id, permission_id=perm.id)
                session.add(role_perm)

            session.commit()
            # capture minimal data to avoid returning a Session-bound instance
            result = {'id': role.id, 'name': role.name}
            return result
        except Exception as e:
            session.rollback()
            raise e
        finally:
            session.close()




class UserCreationForm(forms.ModelForm):
    password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), label="Password")
    confirm_password = forms.CharField(widget=forms.PasswordInput(attrs={'class': 'form-control'}), label="Confirm Password")
    role_id = forms.ChoiceField(label="Assign Role", widget=forms.Select(attrs={'class': 'form-select'}))

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        session = SessionLocal()
        try:
            roles = session.query(Role).all()
            choices = [('', '--------- Select Role ---------')] + [(r.id, r.name) for r in roles]
            self.fields['role_id'].choices = choices
        finally:
            session.close()

    def clean(self):
        cleaned_data = super().clean()
        pw = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm_password')
        if pw and confirm and pw != confirm:
            raise forms.ValidationError("Passwords do not match!")
        return cleaned_data