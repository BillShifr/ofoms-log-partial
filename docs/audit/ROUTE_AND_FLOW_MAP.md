# Карта маршрутов и потоков

| Поток | Маршруты | Доступ | Состояние |
|---|---|---|---|
| Обращение | `/journal/` → `new` → `<id>` → edit/answer/redirect/cover/print | login + org scope | CRUD частично; нет печати списка/FSM |
| Файл обращения | upload → `/journal/files/<id>/download/` | доступ к родительскому Irp | защищено object ACL |
| Обмен | `/exchange/upload/` → logs → protocol | login + org scope | не atomic, нужны quotas |
| Отчёт | `/reports/` → `<slug>` → export | login + org scope | 9 registry items, нет эталонных приложений |
| Сообщения | `/system/messages/` → conversation → thread → reply | participant membership | базовый поток есть; unread требует исправления |
| Вложение сообщения | `/system/messages/attachments/<id>/download/` | participant membership | защищено object ACL |
| Задачи | `/system/tasks/` → create/update/run/toggle | admin | manual/schedule есть; concurrency gap |
| Файл задачи | `/system/tasks/files/<id>/download/` | admin | защищено role check |
| Документы | `/system/docs/` → category/download | login; manage admin | download endpoint есть |
| Пользователи/события | `/system/users/`, `/system/events/` | admin | CRUD/filter есть |

