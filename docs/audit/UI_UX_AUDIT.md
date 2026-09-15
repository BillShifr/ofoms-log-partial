# UX UI аудит

## Критические находки и состояние

- Строки таблиц, карточки и сортировка доступны с клавиатуры; связанные строки задачи/лога и события/детали сортируются одной группой.
- Labels, help text и ошибки стандартных `.field` связаны с контролом; invalid-state получает `aria-invalid`, динамическая подсказка — `role=alert`.
- Непрочитанные сообщения отмечаются прочитанными только при открытии конкретной темы.
- Отсутствовавшие CSS aliases добавлены, палитра тёмной темы выровнена.
- Пагинация использует Django `{% querystring %}`: текущий `page` заменяется, остальные фильтры сохраняются.
- Mobile navigation остаётся одной прокручиваемой строкой; master/detail сообщений показывает активную работу перед каталогом диалогов.
- Полная матрица разрешений, темы, масштаба шрифта, ролей и состояний выполняется по `EXECUTION_PLAN.md`.

## Первая UX вертикаль

Сценарий `реестр → карточка → редактирование → сохранение`: реальные ссылки и доступная сортировка, единый field renderer с ARIA-ошибками, исправленная пагинация, системные CSS tokens, reduced motion, keyboard-only и 1024/1366/1920 browser checks.

## Приёмочный аудит 2026-09-15

Baseline: `.artifacts/visual-qa/baseline/` — 840 browser-cases, 39 автоматических
failures. После исправлений: `.artifacts/visual-qa/after/` — 813 основных cases,
54 permission/403 cases и 81 production error-page case, во всех итоговых отчётах
0 failures.

Ручной просмотр выявил повторяющиеся причины:

- журнал оставался широкой таблицей на 768 px; владелец `DataTable` переведён в
  card grid до 900 px;
- `.text-muted` внутри поля наследовал полный размер `A++`, а нативный file input
  теснил composer; общий `Field` contract получил компактный help text, устойчивый
  file control и одноколоночный embedded form layout до 900 px;
- error-page actions удерживали intrinsic min-content ширину; общий error surface
  получил mobile reflow до 480 px;
- route filter visual runner не фильтровал print routes и применял DataTable checks
  к ожидаемому 403; screen/print selection и expected HTTP statuses унифицированы.

Проверены журнал, задачи, отчёты, сообщения, документация, новости, обмен,
пользователи, события, настройки, login, 403/404/500 и три печатных представления.
Репрезентативные доказательства: `.artifacts/visual-qa/after/journal-768x1024-light-a-plus-plus-default.png`,
`.artifacts/visual-qa/after/message-thread-768x1024-light-a-plus-plus-default.png`,
`.artifacts/visual-qa/after/exchange-protocol-390x844-light.png`,
`.artifacts/visual-qa/after/errors/error-404-390x844-light.png` и
`.artifacts/visual-qa/after/print-rendered/`.
