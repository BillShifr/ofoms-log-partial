# Матрица покрытия требований

Приоритет источников: оригинальное ТЗ и письмо ФФОМС как доменный нормативный контекст, текущий запрос, `PROMPT_v3_УЛУЧШЕННЫЙ.md`, прочие документы, реализация. Письмо ФФОМС содержит методические рекомендации и не заменяет договорное ТЗ.

| Требование | Источник | Роли | Модуль/маршрут | Реализация | Проверка | Разрыв | Статус |
|---|---|---|---|---|---|---|---|
| Реестр, карточка, маркировка, поиск и сортировка | ТЗ 2.1 | ТФОМС, СМО | journal | models/views/templates | Django tests | Нет печати списка; infinite scroll не реализован | частично |
| 4 способа регистрации и единый ФЛК | ТЗ 2.2 | ТФОМС, СМО | journal/exchange | forms/importers/command | exchange tests | Нет доказательства идентичного ФЛК; импорт не atomic | частично |
| История, результат, переадресация, предварительный ответ | ТЗ 2.3 | ОП/СП | journal | IrpHistory/answers/redirect | routing tests | Нет формальной FSM/transition permissions | частично |
| Ролевой deny-by-default доступ | ТЗ 2.4, 3.1 | Admin, ОП, СП, СМО | core/journal/exchange | groups + org scope | отдельные permission tests | Нет полной action matrix | реализовано неверно |
| 9 отчётных форм и фильтры | ТЗ 2.5 | ТФОМС, СМО | reports | registry/export | reports tests | Нет оригинальных Приложений 1–9 | неоднозначно |
| Защищённая выдача вложений | ТЗ 3.1 | все | journal/system downloads | object-scoped FileResponse | regression tests | Web-сервер не должен публиковать media напрямую | реализовано |
| Блокировка после 10 попыток и стойкие пароли | ТЗ 3.1 | все | core/auth | backend/signals/validator | core tests | Счётчик подвержен гонке; окно не используется | частично |
| Временные токены и единый репозиторий | ТЗ 3.1 | все | core/tokens | token helpers | unit tests | Нет интеграционного endpoint/repository adapter | отсутствует |
| Персональные настройки таблиц | ТЗ 3.2 | все | system/prefs | UserTableViewPref | tests | Фиксация/группировка ограничены журналом | частично |
| Сообщения | ТЗ 3.3 | все | system/messages | conversations/threads/replies | tests | Семантика unread нарушена на экране диалога | частично |
| События с start/end и фильтрами | ТЗ 3.4 | Admin | system/events | EventLog/middleware | tests | finished_at не заполняется согласованно | частично |
| Пользователи, группы и права | ТЗ 3.5 | Admin | system/users | CRUD/groups | tests | Нет UI матрицы granular permissions | частично |
| Автоматизированные задачи manual/schedule | ТЗ 3.6 | Admin | system/tasks | registry/runs/command | tests | Нет блокировки параллельного запуска | частично |

