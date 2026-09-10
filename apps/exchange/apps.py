from django.apps import AppConfig


class ExchangeConfig(AppConfig):
    name = "apps.exchange"
    verbose_name = "Обмен данными (ФЛК)"

    def ready(self):
        # Импорт схем/констант при запуске не требуется (загрузка по требованию).
        return None
