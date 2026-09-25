from django.apps import AppConfig


class ExchangeConfig(AppConfig):
    name = "apps.exchange"
    verbose_name = "Обмен данными (ФЛК)"

    def ready(self):
        # схемы и константы загружаются по требованию
        return None
