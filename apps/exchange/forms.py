"""Формы экрана обмена."""

from django import forms


class UploadFileForm(forms.Form):
    """Загрузка файла обмена (XML/Excel) с указанием организации-отправителя."""

    org = forms.ChoiceField(label="Организация (отправитель)")
    file = forms.FileField(
        label="Файл обмена (G1*.xml, users*.xml, *.xlsx)",
        widget=forms.ClearableFileInput(
            attrs={"accept": ".xml,.xlsx,.xls"}
        ),
    )

    def __init__(self, *args, user=None, org_choices=None, **kwargs):
        super().__init__(*args, **kwargs)
        if org_choices:
            self.fields["org"].choices = org_choices

    def clean_file(self):
        uploaded = self.cleaned_data["file"]
        name_lower = (uploaded.name or "").lower()
        known = name_lower.startswith(("users", "g1")) and name_lower.endswith(
            ".xml"
        ) or name_lower.endswith(".xlsx")
        if not known:
            raise forms.ValidationError(
                "Неизвестный тип файла: ожидается G1*.xml, users*.xml или *.xlsx"
            )
        return uploaded
