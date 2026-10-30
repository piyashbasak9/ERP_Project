from io import BytesIO
from pathlib import Path

from django import forms
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, UnidentifiedImageError

from core.common.upload_validation import (
    detect_upload_mime,
    validate_kyc_file,
    validate_upload_size,
)

from .models import Branch, BranchHoliday, Center, Group, Member, MemberKYC, Staff


class BranchForm(forms.ModelForm):
    class Meta:
        model = Branch
        fields = [
            'name', 'code', 'branch_type', 'parent', 'address', 'phone', 'email',
            'opening_date', 'business_date', 'branch_manager',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'branch_type': forms.Select(attrs={'class': 'form-select'}),
            'parent': forms.Select(attrs={'class': 'form-select'}),
            'address': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'opening_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'business_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'branch_manager': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        accessible_ids = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['parent'].queryset = Branch.unscoped.filter(
            pk__in=accessible_ids, is_active=True
        ).order_by('name')
        self.fields['branch_manager'].queryset = Staff.objects.filter(is_active=True).order_by('full_name')
        self.fields['parent'].required = False
        self.fields['branch_manager'].required = False

    def clean(self):
        cleaned = super().clean()
        branch_type = cleaned.get('branch_type')
        parent = cleaned.get('parent')
        if (
            branch_type in {Branch.BRANCH_TYPE_REGION, Branch.BRANCH_TYPE_AREA}
            and not parent
        ):
            self.add_error("parent", "A parent is required for regions and areas.")
        if (
            parent
            and self.instance.pk
            and (
                parent.pk == self.instance.pk
                or parent.hierarchy_path.startswith(self.instance.hierarchy_path)
            )
        ):
            self.add_error("parent", "This parent would create a hierarchy cycle.")
        return cleaned


class CenterForm(forms.ModelForm):
    class Meta:
        model = Center
        fields = ['branch', 'name', 'code', 'meeting_day', 'meeting_time', 'location', 'field_officer']
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
            'meeting_day': forms.TextInput(attrs={'class': 'form-control'}),
            'meeting_time': forms.TimeInput(attrs={'class': 'form-control', 'type': 'time'}),
            'location': forms.TextInput(attrs={'class': 'form-control'}),
            'field_officer': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['branch'].queryset = Branch.unscoped.filter(
            pk__in=request.user.accessible_branch_ids(request.active_branch_id), is_active=True
        )
        self.fields['field_officer'].queryset = Staff.objects.filter(is_active=True)

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get('branch')
        officer = cleaned.get('field_officer')
        if branch and officer and officer.branch_id != branch.id:
            self.add_error('field_officer', 'The field officer must belong to this branch.')
        return cleaned


class GroupForm(forms.ModelForm):
    class Meta:
        model = Group
        fields = ['branch', 'center', 'name', 'code']
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'center': forms.Select(attrs={'class': 'form-select'}),
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'code': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(pk__in=allowed, is_active=True)
        self.fields['center'].queryset = Center.unscoped.filter(branch_id__in=allowed, is_active=True)
        self.fields['center'].required = False

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get('branch')
        center = cleaned.get('center')
        if branch and center and center.branch_id != branch.id:
            self.add_error('center', 'The center must belong to the selected branch.')
        return cleaned


class StaffForm(forms.ModelForm):
    class Meta:
        model = Staff
        fields = ['branch', 'user', 'full_name', 'phone', 'designation', 'assigned_centers']
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'user': forms.Select(attrs={'class': 'form-select'}),
            'full_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone': forms.TextInput(attrs={'class': 'form-control'}),
            'designation': forms.TextInput(attrs={'class': 'form-control'}),
            'assigned_centers': forms.SelectMultiple(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(pk__in=allowed, is_active=True)
        self.fields['assigned_centers'].queryset = Center.unscoped.filter(branch_id__in=allowed, is_active=True)
        self.fields['user'].required = False

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get('branch')
        if branch and any(center.branch_id != branch.id for center in cleaned.get('assigned_centers', [])):
            self.add_error('assigned_centers', 'Every assigned center must belong to the selected branch.')
        user = cleaned.get('user')
        if user and user.branch_id and branch and user.branch_id != branch.id:
            self.add_error('user', 'The user account must be assigned to the same branch.')
        return cleaned


class BranchHolidayForm(forms.ModelForm):
    class Meta:
        model = BranchHoliday
        fields = ["branch", "date", "name", "is_active"]
        widgets = {
            "branch": forms.Select(attrs={"class": "form-select"}),
            "date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields["branch"].queryset = Branch.unscoped.filter(
            pk__in=allowed, is_active=True
        )

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get("branch")
        if branch and branch.pk not in self.fields["branch"].queryset.values_list(
            "pk", flat=True
        ):
            self.add_error("branch", "Select an accessible branch.")
        return cleaned


class DayEndCloseForm(forms.Form):
    branch = forms.ModelChoiceField(
        queryset=Branch.unscoped.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    cash_count = forms.DecimalField(
        min_value=0,
        max_digits=18,
        decimal_places=2,
        widget=forms.NumberInput(
            attrs={"class": "form-control", "min": "0", "step": "0.01"}
        ),
    )
    cash_difference_reason = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )
    carryover_note = forms.CharField(
        required=False,
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.unscoped.filter(
            pk__in=request.user.accessible_branch_ids(request.active_branch_id),
            is_active=True,
        )


class DayEndReopenForm(forms.Form):
    branch = forms.ModelChoiceField(
        queryset=Branch.unscoped.none(),
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    business_date = forms.DateField(
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"})
    )
    reason = forms.CharField(
        max_length=500,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2}),
    )

    def __init__(self, *args, request, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["branch"].queryset = Branch.unscoped.filter(
            pk__in=request.user.accessible_branch_ids(request.active_branch_id),
            is_active=True,
        )


class MemberForm(forms.ModelForm):
    class Meta:
        model = Member
        fields = [
            'branch', 'center', 'group', 'first_name', 'last_name', 'father_name', 'mother_name',
            'spouse_name', 'date_of_birth', 'gender', 'marital_status', 'phone', 'alternate_phone',
            'email', 'present_address', 'permanent_address', 'national_id', 'other_id_numbers',
            'occupation', 'monthly_income', 'household_size', 'admission_date', 'admission_fee',
            'photo',
        ]
        widgets = {
            'branch': forms.Select(attrs={'class': 'form-select'}),
            'center': forms.Select(attrs={'class': 'form-select'}),
            'group': forms.Select(attrs={'class': 'form-select'}),
            'date_of_birth': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'admission_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'monthly_income': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'admission_fee': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0'}),
            'photo': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/jpeg,image/png'}),
        }

    def __init__(self, *args, request, **kwargs):
        self.request = request
        super().__init__(*args, **kwargs)
        allowed = request.user.accessible_branch_ids(request.active_branch_id)
        self.fields['branch'].queryset = Branch.unscoped.filter(pk__in=allowed, is_active=True)
        self.fields['center'].queryset = Center.unscoped.filter(branch_id__in=allowed, is_active=True)
        self.fields['group'].queryset = Group.unscoped.filter(branch_id__in=allowed, is_active=True)
        self.fields['center'].required = False
        self.fields['group'].required = False
        self.fields['photo'].required = False

    def clean_photo(self):
        uploaded = self.cleaned_data.get('photo')
        if not isinstance(uploaded, UploadedFile):
            return uploaded
        validate_upload_size(uploaded)
        mime_type = detect_upload_mime(uploaded)
        if mime_type not in {'image/jpeg', 'image/png'}:
            raise forms.ValidationError('Photo must be a JPG or PNG image.')
        try:
            uploaded.seek(0)
            image = Image.open(uploaded)
            image.verify()
            uploaded.seek(0)
            image = Image.open(uploaded).convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=90, optimize=True)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise forms.ValidationError('The uploaded image is invalid.') from exc
        return ContentFile(output.getvalue(), name='member-photo.jpg')

    def clean(self):
        cleaned = super().clean()
        branch = cleaned.get('branch')
        center = cleaned.get('center')
        group = cleaned.get('group')
        if center and branch and center.branch_id != branch.id:
            self.add_error('center', 'The center must belong to the selected branch.')
        if group and branch and group.branch_id != branch.id:
            self.add_error('group', 'The group must belong to the selected branch.')
        if center and group and group.center_id not in {None, center.id}:
            self.add_error('group', 'The group must belong to the selected center.')
        return cleaned


class MemberKYCForm(forms.ModelForm):
    class Meta:
        model = MemberKYC
        fields = [
            'document_type', 'document_number', 'issue_date', 'expiry_date', 'file', 'notes',
        ]
        widgets = {
            'document_type': forms.Select(attrs={'class': 'form-select'}),
            'document_number': forms.TextInput(attrs={'class': 'form-control'}),
            'issue_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'expiry_date': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'file': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': '.jpg,.jpeg,.png,.pdf'}),
            'notes': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['file'].required = True

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('document_type') == MemberKYC.DOC_TYPE_PHOTO and getattr(
            self, 'mime_type', ''
        ) not in {'image/jpeg', 'image/png'}:
            self.add_error('file', 'A photo KYC document must be a JPG or PNG image.')
        return cleaned

    def clean_file(self):
        uploaded = self.cleaned_data.get('file')
        if not uploaded:
            return uploaded
        validate_kyc_file(uploaded)
        self.mime_type = detect_upload_mime(uploaded)
        original = Path(uploaded.name).name
        self.file_name = ''.join(char for char in original if char.isalnum() or char in ' ._-')[:200]
        if not self.file_name:
            self.file_name = 'document'
        return uploaded

    def save(self, commit=True):
        instance = super().save(commit=False)
        if hasattr(self, 'mime_type'):
            instance.mime_type = self.mime_type
            instance.file_name = self.file_name
        if commit:
            instance.save()
        return instance


class MemberStatusForm(forms.Form):
    status = forms.ChoiceField(choices=Member.STATUS_CHOICES, widget=forms.Select(attrs={'class': 'form-select'}))
    reason = forms.CharField(max_length=255, widget=forms.TextInput(attrs={'class': 'form-control'}))
