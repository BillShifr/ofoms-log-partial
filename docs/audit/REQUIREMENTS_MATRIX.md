# Матрица покрытия требований

Приоритет источников: оригинальное ТЗ и письмо ФФОМС как доменный нормативный контекст, текущий запрос, `PROMPT_v3_УЛУЧШЕННЫЙ.md`, прочие документы, реализация. Письмо ФФОМС содержит методические рекомендации и не заменяет договорное ТЗ.

| Требование | Источник | Роли | Модуль/маршрут | Реализация | Проверка | Разрыв | Статус |
|---|---|---|---|---|---|---|---|
| Реестр, карточка, маркировка, поиск и сортировка | ТЗ 2.1 | ТФОМС, СМО | journal | models/views/templates/print list + progressive infinite scroll | Django/browser tests | Серверная пагинация остаётся доступным fallback; при JavaScript следующие страницы автоматически добавляются с сохранением query-state | реализовано |
| 4 способа регистрации и единый ФЛК | ТЗ 2.2 | ТФОМС, СМО | journal/exchange | forms/importers/command | exchange tests | Импорт atomic; нет эталонного Приложения 10 для доказательства формата | частично |
| История, результат, переадресация, предварительный ответ | ТЗ 2.3 | ОП/СП | journal | IrpHistory/answers/redirect + persisted FSM | routing/lifecycle tests | Детальные цепочки назначения по линиям требуют эталонной оргструктуры | частично |
| Ролевой deny-by-default доступ | ТЗ 2.4, 3.1 | Admin, ОП, СП, СМО | core/journal/exchange/reports | capability policy + org scope + terminal-state guards | permission/lifecycle tests | Детальные destination rules зависят от оргструктуры | реализовано |
| 9 отчётных форм и фильтры | ТЗ 2.5 | ТФОМС, СМО | reports | registry/export + SQL aggregation | result/query-count reports tests | Нет оригинальных Приложений 1–9 | неоднозначно |
| Защищённая выдача вложений | ТЗ 3.1 | все | journal/system downloads | object-scoped FileResponse | regression tests | Web-сервер не должен публиковать media напрямую | реализовано |
| Блокировка после 10 попыток и стойкие пароли | ТЗ 3.1 | все | core/auth | backend/signals/atomic counter/validator | core + employee tests | Временное окно намеренно не применяется: разблокировка только администратором | реализовано |
| Временные токены и единый репозиторий | ТЗ 3.1 | все | core/tokens, core/token-login | Одноразовый JWT exchange + Employee repository adapter | unit/view/replay tests | POST-only обмен; обязательный уникальный `jti`; atomic consume; inactive/locked deny; safe redirect | реализовано |
| Персональные настройки таблиц | ТЗ 3.2 | все | system/prefs, journal/list | UserTableViewPref | view tests | Видимость, сохранённый порядок, сортировка, фиксация и групповые заголовки применяются к реестру | реализовано |
| Сообщения | ТЗ 3.3 | все | system/messages | conversations/threads/replies/read markers | view + permission tests | Нет realtime; базовый поток и unread корректны | реализовано |
| События с start/end и фильтрами | ТЗ 3.4 | Admin | system/events | EventLog/middleware + point/pending lifecycle | model/view tests | — | реализовано |
| Пользователи, группы и права | ТЗ 3.5 | Admin | system/users | CRUD/known roles/org validation/capability matrix | form/view tests | Период действия ролей не добавлялся: такого требования нет в первоисточнике | реализовано |
| Автоматизированные задачи manual/schedule | ТЗ 3.6 | Admin | system/tasks + compose scheduler | registry/runs/atomic claim/stale recovery | view/command/compose checks | Отдельный scheduler поставляется; зависшие запуски закрываются по настраиваемому таймауту | реализовано |
| Эксплуатационная документация и видеоролики | ТЗ 3.7 | Admin, все пользователи | system/docs | защищённая загрузка/каталог/view/download | upload, view, ACL и validator tests | Документы до 20 МБ; MP4/WebM/OGV до 200 МБ; видео доступно для просмотра только после входа; исполняемые форматы запрещены | реализовано |
