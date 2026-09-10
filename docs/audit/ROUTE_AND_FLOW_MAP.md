# Карта маршрутов и потоков

| Поток | Маршруты | Доступ | Состояние |
|---|---|---|---|
| Обращение | `/journal/` → `new` → `<id>` → edit/answer/redirect/cover/print; `/journal/print/` | capability + org scope | CRUD, печать карточки/списка и persisted FSM |
| Файл обращения | upload → `/journal/files/<id>/download/` | доступ к родительскому Irp | защищено object ACL |
| Обмен | `/exchange/upload/` → logs → protocol | capability + org scope | atomic import, quotas, secure XML parser и FLCP |
| Отчёт | `/reports/` → `<slug>` → export | login + org scope | 9 registry items, нет эталонных приложений |
| Сообщения | `/system/messages/` → conversation → thread → reply | participant membership | unread сохраняется до открытия конкретной темы; N+1 устранён |
| Вложение сообщения | `/system/messages/attachments/<id>/download/` | participant membership | защищено object ACL |
| Задачи | `/system/tasks/` → create/update/run/toggle | admin | manual/schedule, atomic claim и stale recovery |
| Файл задачи | `/system/tasks/files/<id>/download/` | admin | защищено role check |
| Документы | `/system/docs/` → category/download | login; manage admin | download endpoint есть |
| Пользователи/события | `/system/users/`, `/system/events/` | admin | CRUD/filter есть |
