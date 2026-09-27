# AGENTS.md

# Инструкция для Codex-агентов проекта Telegram Task Bot

## 1. Назначение файла

Этот файл определяет, как разделять разработку Telegram-бота управления задачами между несколькими Codex-агентами.

Главная цель разделения:

- параллелить независимую работу;
- не допускать, чтобы несколько агентов одновременно проектировали одни и те же сущности;
- уменьшить количество конфликтов при merge;
- сохранить одну общую архитектуру;
- обеспечить проверку проекта отдельным интеграционным агентом.

Этот файл является обязательной инструкцией для всех агентов проекта.

Функциональные требования определяются основным техническим заданием проекта. Если между реализацией агента и ТЗ есть противоречие, приоритет имеет ТЗ.

---

# 2. Общая стратегия разработки

Разработка выполняется в три стадии.

```text
СТАДИЯ 1

Agent 1
Architecture / Foundation
        |
        v
Общий архитектурный фундамент зафиксирован
        |
        v

СТАДИЯ 2

Agent 2            Agent 3             Agent 4
Telegram / UX      Scheduler           Task Business Logic
     \                 |                    /
      \                |                   /
       +---------------+------------------+
                       |
                       v

СТАДИЯ 3

Agent 5
Integration / QA / Final Fixes
```

Agent 1 всегда выполняется первым.

Agents 2, 3 и 4 запускаются только после того, как изменения Agent 1 закоммичены и доступны как единая исходная база.

Agents 2, 3 и 4 можно запускать параллельно.

Agent 5 запускается после объединения работы Agents 2, 3 и 4.

---

# 3. Обязательное правило для всех агентов

Перед началом работы каждый агент обязан:

1. Прочитать полное техническое задание проекта.
2. Прочитать этот `AGENTS.md`.
3. Изучить существующую структуру репозитория.
4. Не менять архитектурные решения, созданные Agent 1, без необходимости.
5. Не переписывать чужую подсистему целиком ради собственного удобства.
6. Не создавать альтернативные реализации уже существующих сервисов.
7. Не дублировать модели, enum, DTO и repository interfaces.
8. Запускать тесты своей области перед завершением задачи.
9. Оставлять проект в запускаемом состоянии.
10. Не коммитить секреты, Telegram Bot Token, пароли PostgreSQL или Redis.

Если найден архитектурный недостаток, который блокирует работу, агент должен внести минимально необходимое совместимое изменение, а не перестраивать проект полностью.

---

# 4. Базовая структура проекта

Agent 1 должен создать структуру, близкую к следующей:

```text
.
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docker-compose.yml
├── Dockerfile
├── alembic.ini
│
├── alembic/
│   ├── env.py
│   └── versions/
│
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── worker.py
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py
│   │
│   ├── bot/
│   │   ├── __init__.py
│   │   ├── setup.py
│   │   ├── handlers/
│   │   ├── keyboards/
│   │   ├── middlewares/
│   │   ├── filters/
│   │   ├── states/
│   │   └── renderers/
│   │
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── session.py
│   │   ├── models/
│   │   └── repositories/
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── enums.py
│   │   ├── schemas.py
│   │   └── exceptions.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── task_service.py
│   │   ├── user_service.py
│   │   ├── recurrence_service.py
│   │   ├── permission_service.py
│   │   └── notification_service.py
│   │
│   ├── scheduler/
│   │   ├── __init__.py
│   │   ├── jobs.py
│   │   ├── worker.py
│   │   └── delivery.py
│   │
│   └── utils/
│       ├── __init__.py
│       ├── datetime.py
│       └── telegram.py
│
├── scripts/
│   ├── backup.sh
│   └── restore.sh
│
└── tests/
    ├── conftest.py
    ├── unit/
    ├── integration/
    └── e2e/
```

Допускаются небольшие изменения структуры, если они не нарушают разделение ответственности агентов.

---

# 5. Общие архитектурные правила

## 5.1 PostgreSQL

PostgreSQL является единственным постоянным источником бизнес-данных.

В PostgreSQL должны храниться:

- пользователи;
- задачи;
- исполнители;
- история задач;
- серии повторяющихся задач;
- внутренние администраторы;
- запланированные уведомления.

---

## 5.2 Redis

Redis используется только для временных данных:

- FSM Telegram;
- временное состояние мастера;
- короткоживущие блокировки;
- предотвращение параллельной обработки одинаковых действий.

Redis не должен быть единственным местом хранения задачи, уведомления или серии повторений.

---

## 5.3 Время

Вся бизнес-логика работает в часовом поясе:

```text
Europe/Moscow
```

Все внутренние datetime рекомендуется хранить timezone-aware.

---

## 5.4 Telegram ID

Главный идентификатор пользователя:

```text
telegram_user_id
```

`username` является изменяемым отображаемым атрибутом и не должен использоваться как внешний ключ.

---

## 5.5 Бизнес-логика

Telegram handlers не должны содержать сложную бизнес-логику.

Правильно:

```text
handler
   |
   v
service
   |
   v
repository
```

Неправильно:

```text
handler
   |
   +--> SQLAlchemy query
   +--> изменение статуса
   +--> расчёт напоминаний
   +--> создание recurrence
```

---

# 6. Agent 1 — Architecture / Foundation

## 6.1 Цель

Создать общий технический фундамент, на котором смогут независимо работать остальные агенты.

Agent 1 не должен реализовывать весь продукт.

Его задача — сделать стабильный каркас и общие контракты.

---

## 6.2 Agent 1 отвечает за

### Инфраструктуру

- `pyproject.toml`;
- зависимости;
- Dockerfile;
- `docker-compose.yml`;
- `.env.example`;
- `.gitignore`;
- базовый README;
- запуск bot process;
- запуск worker process;
- PostgreSQL;
- Redis;
- healthchecks контейнеров.

### Конфигурацию

Обязательные настройки:

```text
BOT_TOKEN
BOT_OWNER_ID
ALLOWED_CHAT_ID
DATABASE_URL
REDIS_URL
TIMEZONE=Europe/Moscow
BACKUP_RETENTION_DAYS=14
```

### Модели БД

Создать модели:

```text
User
Task
TaskAssignee
TaskEvent
RecurrenceSeries
InternalAdmin
ScheduledNotification
```

### Enum

Зафиксировать enum:

```text
TaskPriority:
LOW
NORMAL
HIGH
URGENT
```

```text
TaskStatus:
NEW
IN_PROGRESS
WAITING_AUTHOR
COMPLETED
CANCELLED
```

Дополнительный флаг `overdue` не должен быть отдельным постоянным основным статусом.

Просрочка вычисляется из `due_at` и текущего состояния.

### Alembic

Создать:

- конфигурацию;
- initial migration;
- возможность выполнить `alembic upgrade head`.

### Базовые repository interfaces

Создать репозитории для основных сущностей.

Минимум:

```text
UserRepository
TaskRepository
TaskEventRepository
RecurrenceRepository
AdminRepository
NotificationRepository
```

### Общие domain schemas

Создать DTO/Pydantic-схемы, которые будут использовать другие агенты.

Например:

```text
TaskCreateData
TaskUpdateData
AssigneeData
RecurrenceConfig
TaskView
NotificationData
```

### Общие exceptions

Например:

```text
TaskNotFound
PermissionDenied
InvalidTaskState
InvalidAssignee
UserNotRegistered
UserNotInChat
InvalidDeadline
```

---

## 6.3 Agent 1 может менять

```text
pyproject.toml
Dockerfile
docker-compose.yml
.env.example
.gitignore
README.md

app/config/**
app/db/**
app/domain/**
app/utils/**

alembic/**
alembic.ini

scripts/**
tests/conftest.py
```

---

## 6.4 Agent 1 не должен

На этой стадии полноценно реализовывать:

- `/task`;
- FSM создания задачи;
- Telegram UI;
- напоминания;
- вечернюю сводку;
- recurrence worker;
- сложные task transitions;
- конечные интеграционные тесты.

Можно оставить минимальные интерфейсы и skeleton implementations, необходимые другим агентам.

---

## 6.5 Критерии завершения Agent 1

Работа считается завершённой, если:

1. `docker compose build` выполняется успешно.
2. PostgreSQL стартует.
3. Redis стартует.
4. Bot container способен стартовать без бизнес-handlers.
5. Worker container способен стартовать.
6. `alembic upgrade head` создаёт БД.
7. Все основные модели существуют.
8. Enum зафиксированы.
9. Repository contracts определены.
10. Domain schemas определены.
11. Секретов в Git нет.
12. Базовые тесты моделей проходят.

Рекомендуемый commit:

```text
chore: bootstrap task bot architecture
```

---

# 7. Agent 2 — Telegram / UX

## 7.1 Цель

Реализовать весь пользовательский Telegram-интерфейс поверх готового service layer.

Agent 2 не должен проектировать собственную альтернативную бизнес-модель задач.

---

## 7.2 Agent 2 отвечает за

### Команды

```text
/start
/task
/tasks
/mytasks
/archive
/help
/admins
```

### Создание задачи

Поддержать:

```text
/task
```

и:

```text
/task Название задачи
```

и упоминание бота с текстом задачи, если это возможно в текущей конфигурации Telegram.

### FSM создания

Шаги:

```text
Название
Описание
Приоритет
Исполнители
Дедлайн
Повторение
Предпросмотр
Подтверждение
```

### Описание

Кнопки:

```text
[Добавить]
[Пропустить]
```

Поддержка текста и ссылок.

### Приоритет

```text
[🟢 Низкий]
[🔵 Обычный]
[🟠 Высокий]
[🔴 Срочный]
```

### Исполнители

Пользователь вводит одним сообщением:

```text
@user1 @user2 @user3
```

Agent 2 вызывает сервис проверки пользователей, а не самостоятельно работает с БД.

### Дедлайн

Принимать только:

```text
ДД.ММ.ГГГГ
```

### Повторение

Интерфейс:

```text
[Да]
[Нет]
```

При `Да`:

1. пользователь вводит положительное число;
2. выбирает:
   - дни;
   - недели;
   - месяцы;
   - годы;
3. указывает дату окончания серии.

### Предпросмотр

Кнопки:

```text
[✅ Создать]
[✏️ Изменить]
[❌ Отмена]
```

### Редактирование до создания

```text
[Название]
[Описание]
[Приоритет]
[Исполнители]
[Дедлайн]
[Повторение]
```

---

## 7.3 Карточка задачи

Agent 2 реализует единый renderer карточки.

Пример:

```text
🟠 Задача #42

Заказать значки

Уточнить количество и форму.

Статус: 🔵 В работе
Приоритет: 🟠 Высокий
Исполнители: @ivanov @petrov
Автор: @author
Создана: 26.09.2026
Дедлайн: 30.09.2026, 23:59
Повторение: нет
```

Inline actions зависят от роли пользователя.

---

## 7.4 Действия исполнителя

```text
[▶️ Начать]
[✅ Выполнено]
[⚠️ Не могу выполнить]
[📋 История]
```

---

## 7.5 Действия автора/админа

Дополнительно:

```text
[📅 Перенести]
[👤 Сменить исполнителя]
[✏️ Изменить]
[❌ Отменить]
```

---

## 7.6 «Не могу выполнить»

Agent 2 реализует UX:

1. пользователь нажимает кнопку;
2. бот просит обязательную причину;
3. вызывает business service;
4. карточка обновляется;
5. автор получает доступные решения.

---

## 7.7 `/tasks`

Фильтры:

```text
Все активные
Мои
Созданные мной
Просроченные
Новые
В работе
```

Сортировка:

```text
По дедлайну
По приоритету
По дате создания
```

Пагинация:

```text
10 задач на страницу
```

---

## 7.8 `/mytasks`

Показывает активные задачи текущего исполнителя.

---

## 7.9 `/archive`

Показывает:

```text
COMPLETED
CANCELLED
```

---

## 7.10 `/start` в ЛС

Регистрирует возможность личных уведомлений.

Меню:

```text
[📋 Мои задачи]
[🔴 Просроченные]
[✅ Завершённые]
```

Создание задачи в ЛС блокируется.

---

## 7.11 `/admins`

UI управления внутренними администраторами.

Agent 2 использует `PermissionService`.

---

## 7.12 Обновление карточек

При обычном изменении состояния необходимо редактировать исходное сообщение задачи.

Не создавать новую карточку на каждое действие.

---

## 7.13 Agent 2 может менять

```text
app/bot/**
app/main.py
tests/unit/bot/**
tests/integration/bot/**
```

При необходимости разрешены минимальные изменения:

```text
app/domain/schemas.py
app/services/* интерфейсы
```

но только если это необходимо для интеграции.

---

## 7.14 Agent 2 не должен

Самостоятельно реализовывать:

- алгоритм recurrence;
- scheduler;
- six-hour overdue logic;
- database models;
- собственные SQL queries в handlers;
- альтернативную permission system.

---

## 7.15 Критерии завершения Agent 2

Должны работать:

1. `/start`.
2. `/task`.
3. `/task Название`.
4. полный FSM.
5. предпросмотр.
6. изменение до создания.
7. карточка задачи.
8. inline actions.
9. `/tasks`.
10. `/mytasks`.
11. `/archive`.
12. `/admins`.
13. пагинация.
14. проверка callback permissions через service layer.
15. редактирование исходной карточки.

Рекомендуемый commit:

```text
feat: implement telegram task interface
```

---

# 8. Agent 3 — Scheduler / Notifications

## 8.1 Цель

Реализовать все временные процессы и доставку уведомлений.

Agent 3 не должен управлять Telegram FSM или изменять основные правила переходов задачи.

---

## 8.2 Agent 3 отвечает за

### Scheduled notifications

Хранение событий в PostgreSQL.

Не держать расписание только в памяти.

### Стандартные напоминания

Для обычной задачи:

```text
за 7 дней — 07:00 МСК
за 3 дня — 07:00 МСК
за 1 день — 07:00 МСК
в день дедлайна — 07:00 МСК
за 3 часа
в момент дедлайна
```

### Срочные задачи

Для `URGENT`:

```text
09:00 МСК
21:00 МСК
```

ежедневно до:

- выполнения;
- отмены;
- WAITING_AUTHOR;
- перехода в overdue-mode.

### Просроченные

После дедлайна:

```text
00:00
06:00
12:00
18:00
```

МСК.

Для всех приоритетов одинаково.

### Daily summary

Каждый день:

```text
20:00 МСК
```

в общую группу.

Разделы:

```text
🔴 Просроченные
⏳ Дедлайн сегодня
📅 Дедлайн завтра
```

В ЛС ежедневная сводка не отправляется.

---

## 8.3 Персональные уведомления

Обычные task reminders отправляются:

1. в группу;
2. в ЛС каждому исполнителю, если private chat активирован.

Ошибка личной доставки не должна ломать group delivery.

---

## 8.4 Deduplication

Каждое scheduled event должно иметь уникальный:

```text
deduplication_key
```

Повторная обработка worker не должна отправлять одно событие дважды.

---

## 8.5 Объединение уведомлений

Если два события одной задачи находятся в пределах 15 минут, их можно объединить.

Пример:

```text
20:59 reminder_before_3_hours
21:00 urgent_reminder
```

=> одно сообщение.

Но:

```text
07:00
09:00
```

не объединяются.

---

## 8.6 Restart safety

После перезапуска:

- будущие уведомления должны сохраниться;
- просроченные pending jobs должны быть обработаны;
- completed notification не должна отправиться второй раз.

---

## 8.7 Retry

При временной ошибке Telegram:

- не терять notification;
- retry с ограниченным backoff;
- фиксировать ошибку в системном логе.

При `bot blocked` в ЛС:

- не retry бесконечно;
- отметить private delivery unavailable;
- group notifications продолжить.

---

## 8.8 Agent 3 может менять

```text
app/scheduler/**
app/services/notification_service.py
app/worker.py
tests/unit/scheduler/**
tests/integration/scheduler/**
```

Допускаются минимальные изменения:

```text
app/db/repositories/notification*
app/domain/schemas.py
```

---

## 8.9 Agent 3 не должен

Менять:

- модели задач без необходимости;
- Telegram FSM;
- task state transitions;
- recurrence business rules;
- admin permission model.

---

## 8.10 Критерии завершения Agent 3

Тестами должны быть подтверждены:

1. 7-day reminder.
2. 3-day reminder.
3. 1-day reminder.
4. same-day 07:00 reminder.
5. 3-hour reminder.
6. deadline reminder.
7. urgent 09:00.
8. urgent 21:00.
9. overdue 00/06/12/18.
10. daily summary 20:00.
11. no past reminders.
12. no reminders after completed.
13. no reminders after cancelled.
14. pause during WAITING_AUTHOR.
15. delivery in group.
16. private delivery when available.
17. safe failure when private delivery unavailable.
18. deduplication.
19. restart recovery.

Рекомендуемый commit:

```text
feat: implement persistent notification scheduler
```

---

# 9. Agent 4 — Task Business Logic / Recurrence

## 9.1 Цель

Реализовать центральную бизнес-логику задач независимо от Telegram UI.

Именно Agent 4 определяет допустимые переходы состояний.

---

## 9.2 Agent 4 отвечает за TaskService

Основные операции:

```text
create_task()
start_task()
complete_task()
mark_unable_to_complete()
resolve_unable_state()
update_task()
reschedule_task()
replace_assignees()
cancel_task()
get_task()
list_tasks()
list_user_tasks()
list_created_tasks()
list_archive()
get_history()
```

---

## 9.3 Проверка исполнителей

Перед назначением:

- пользователь должен быть известен;
- должен иметь username;
- должен состоять в рабочей группе;
- актуальное членство при необходимости проверяется через abstraction Telegram membership provider.

Не выполнять Telegram API вызовы непосредственно из repository.

---

## 9.4 Переходы состояний

Основная модель:

```text
NEW
  |
  v
IN_PROGRESS
  |
  v
COMPLETED
```

Дополнительно:

```text
WAITING_AUTHOR
CANCELLED
```

---

## 9.5 Начало

Только исполнитель:

```text
NEW -> IN_PROGRESS
```

---

## 9.6 Выполнение

Завершить задачу могут:

- любой исполнитель;
- автор;
- внутренний администратор.

Если исполнителей несколько, завершение одним закрывает всю задачу.

---

## 9.7 Не могу выполнить

Исполнитель обязан указать причину.

После этого:

```text
NEW / IN_PROGRESS
        |
        v
WAITING_AUTHOR
```

Нужно сохранить предыдущий рабочий статус, чтобы при новом дедлайне с тем же исполнителем корректно восстановить:

- `NEW`, если задача ещё не начиналась;
- `IN_PROGRESS`, если уже была в работе.

Если меняется исполнитель:

```text
WAITING_AUTHOR -> NEW
```

---

## 9.8 Перенос

Переносить дедлайн могут:

- автор;
- внутренний администратор.

Исполнитель без этих ролей не может.

Дата раньше текущего дня запрещена.

---

## 9.9 Отмена

Только:

- автор;
- внутренний администратор.

Причина обязательна.

---

## 9.10 История

Каждое бизнес-событие сохраняется в `TaskEvent`.

Необходимые события:

```text
TASK_CREATED
TASK_STARTED
TASK_COMPLETED
TASK_CANCELLED
TASK_UNABLE
TASK_RESOLVED
TITLE_CHANGED
DESCRIPTION_CHANGED
PRIORITY_CHANGED
ASSIGNEES_CHANGED
DEADLINE_CHANGED
RECURRENCE_CHANGED
RECURRENCE_INSTANCE_CREATED
```

---

# 10. Agent 4 — Recurrence

## 10.1 Интервалы

Поддержать:

```text
N days
N weeks
N months
N years
```

Часы не поддерживать.

---

## 10.2 Окончание серии

У каждой серии обязательно есть:

```text
end_date
```

После неё новые экземпляры не создаются.

---

## 10.3 Расчёт дат

Следующий дедлайн считается от исходного recurrence schedule, а не от даты выполнения.

Пример:

```text
base due: 01.10.2026
interval: 1 month
```

Даты:

```text
01.10.2026
01.11.2026
01.12.2026
```

Даже если первая задача выполнена:

```text
28.09.2026
```

---

## 10.4 Раннее завершение

Если текущий экземпляр выполнен раньше срока, следующий экземпляр создаётся сразу.

---

## 10.5 Невыполненный предыдущий экземпляр

Если наступает новый период, новый экземпляр создаётся независимо от предыдущего.

Разрешено одновременно:

```text
старый экземпляр — overdue
новый экземпляр — NEW
```

---

## 10.6 Защита от дублей

Для комбинации:

```text
recurrence_series_id
scheduled_due_at
```

должна существовать уникальность.

Один период не может создать два экземпляра.

---

## 10.7 Изменение серии

При изменении повторяющейся задачи:

- изменить текущую задачу;
- изменить шаблон будущих экземпляров;
- не менять прошлые completed/cancelled instances.

UI предупреждения реализует Agent 2.

---

## 10.8 Остановка серии

После `end_date` новые экземпляры не создаются.

Также серия может быть деактивирована автором/администратором в рамках редактирования recurrence.

---

## 10.9 Выход пользователя из группы

При событии выхода исполнителя:

- активные задачи не удалять;
- найти активные задачи;
- создать business event;
- инициировать уведомление автору/админу через notification abstraction.

---

## 10.10 PermissionService

Agent 4 реализует централизованные проверки:

```text
can_start()
can_complete()
can_edit()
can_reschedule()
can_change_assignees()
can_cancel()
can_manage_admins()
```

Telegram handlers используют эти методы.

---

## 10.11 Agent 4 может менять

```text
app/services/task_service.py
app/services/user_service.py
app/services/recurrence_service.py
app/services/permission_service.py

app/db/repositories/task*
app/db/repositories/user*
app/db/repositories/recurrence*
app/db/repositories/admin*
app/db/repositories/event*

tests/unit/services/**
tests/integration/services/**
```

---

## 10.12 Agent 4 не должен

Менять без необходимости:

```text
app/bot/**
app/scheduler/**
Docker infrastructure
Alembic base architecture
```

---

## 10.13 Критерии завершения Agent 4

Покрыть тестами:

1. создание задачи;
2. обязательный исполнитель;
3. обязательный дедлайн;
4. invalid deadline;
5. multiple assignees;
6. start by assignee;
7. deny start by stranger;
8. complete by any assignee;
9. complete by author;
10. complete by admin;
11. unable with reason;
12. reject unable without reason;
13. WAITING_AUTHOR;
14. new deadline resolution;
15. replace assignee -> NEW;
16. cancel with reason;
17. reject cancel without reason;
18. history events;
19. recurrence days;
20. recurrence weeks;
21. recurrence months;
22. recurrence years;
23. recurrence end date;
24. early completion next instance;
25. overdue previous + new next instance;
26. duplicate protection;
27. permissions;
28. user leaving chat.

Рекомендуемый commit:

```text
feat: implement task and recurrence business logic
```

---

# 11. Agent 5 — Integration / QA / Final Fixes

## 11.1 Когда запускать

Agent 5 запускается только после того, как изменения Agents 2, 3 и 4 объединены в одну ветку.

---

## 11.2 Цель

Agent 5 не разрабатывает проект заново.

Его задача:

- интегрировать;
- найти несоответствия;
- исправить несовместимости;
- проверить ТЗ;
- проверить edge cases;
- довести проект до запускаемого состояния.

---

## 11.3 Agent 5 обязан сначала

Выполнить:

```bash
docker compose build
docker compose up -d
docker compose ps
```

Затем:

```bash
alembic upgrade head
```

и весь test suite.

---

## 11.4 Интеграционные сценарии

Agent 5 должен проверить полный пользовательский поток.

### Сценарий A

```text
/task
-> название
-> описание
-> приоритет
-> исполнитель
-> дедлайн
-> без recurrence
-> preview
-> create
-> start
-> complete
```

### Сценарий B

```text
/task Название
-> multiple assignees
-> urgent
-> deadline
-> create
-> one assignee completes
-> entire task completed
```

### Сценарий C

```text
create
-> start
-> unable to complete
-> reason
-> WAITING_AUTHOR
-> new deadline
-> IN_PROGRESS
```

### Сценарий D

```text
create
-> unable
-> author replaces assignee
-> status NEW
```

### Сценарий E

```text
recurring monthly task
-> complete early
-> next task created with original schedule
```

### Сценарий F

```text
recurring task overdue
-> next scheduled instance created anyway
```

### Сценарий G

```text
deadline reached
-> overdue
-> reminder every 6 hours
```

### Сценарий H

```text
20:00
-> daily digest contains overdue + today + tomorrow
```

### Сценарий I

```text
assignee did not start bot in private
-> group notification succeeds
-> private notification fails safely
```

### Сценарий J

```text
assignee leaves group
-> active task preserved
-> author/admin notified
```

---

# 12. Agent 5 — Конкурентные сценарии

Проверить:

### Double complete

Два исполнителя одновременно нажимают:

```text
✅ Выполнено
```

Результат:

- одна транзакция завершает задачу;
- одно completion event;
- нет ошибки состояния;
- нет двух сообщений.

### Complete vs reminder

Worker начинает отправку в тот же момент, когда пользователь завершает задачу.

Необходимо минимизировать отправку уже неактуального reminder.

### Recurrence race

Два worker process одновременно пытаются создать один recurrence instance.

Результат:

```text
1 task
```

а не две.

### Reschedule vs complete

Автор переносит дедлайн одновременно с завершением.

Система должна сохранить консистентное финальное состояние.

---

# 13. Agent 5 — Security review

Проверить:

- callback нельзя подделать для управления чужой задачей;
- permission check выполняется server-side;
- BOT_TOKEN не попадает в logs;
- `.env` не коммитится;
- SQL injection невозможен через ORM usage;
- arbitrary chat не может использовать бота;
- `ALLOWED_CHAT_ID` реально проверяется;
- user_id является authoritative identity;
- username не используется как security identity.

---

# 14. Agent 5 — Persistence review

Проверить перезапуск:

```bash
docker compose restart bot worker
```

После рестарта должны сохраниться:

- задачи;
- FSM-завершённые данные;
- история;
- recurrence series;
- будущие notifications;
- internal admins.

Временный незавершённый FSM допускается хранить в Redis и переживать рестарт Redis только если persistence Redis настроен. Если Redis persistence не используется, допустимо потерять только незавершённый мастер создания задачи, но не созданную задачу.

---

# 15. Agent 5 — Backup review

Проверить:

- backup запускается ежедневно в 03:00 МСК;
- создаётся валидный PostgreSQL dump;
- retention равен 14 копиям;
- restore script способен восстановить тестовую БД.

---

# 16. Agent 5 может менять

Agent 5 может изменять любые файлы проекта, если изменение необходимо для исправления интеграции или выполнения ТЗ.

Но Agent 5 не должен без причины полностью переписывать готовые подсистемы.

---

# 17. Критерии завершения Agent 5

Проект считается готовым только если:

```bash
docker compose build
```

успешен;

```bash
docker compose up -d
```

успешен;

```bash
alembic upgrade head
```

успешен;

все automated tests проходят;

основные e2e сценарии проходят;

нет критических race conditions;

нет известных расхождений с ТЗ.

Рекомендуемый commit:

```text
test: integrate and validate telegram task bot
```

или, если потребовались исправления:

```text
fix: resolve integration issues and finalize MVP
```

---

# 18. Git / Worktree стратегия

Рекомендуемая схема.

После Agent 1:

```text
main
└── foundation commit
```

Создать три независимые ветки/worktree:

```text
agent/telegram
agent/scheduler
agent/tasks
```

Все они должны начинаться от одного foundation commit.

После завершения:

```text
agent/telegram
      \
agent/scheduler ----> integration
      /
agent/tasks
```

После merge:

```text
integration
    |
    v
Agent 5
    |
    v
main
```

---

# 19. Правила изменения файлов между агентами

## Agent 2 owner

```text
app/bot/**
```

## Agent 3 owner

```text
app/scheduler/**
app/services/notification_service.py
app/worker.py
```

## Agent 4 owner

```text
app/services/task_service.py
app/services/user_service.py
app/services/recurrence_service.py
app/services/permission_service.py
```

## Shared

Следующие файлы считаются shared и должны изменяться осторожно:

```text
app/domain/**
app/db/models/**
app/db/repositories/**
app/config/**
```

После завершения Agent 1 остальные агенты должны избегать изменения shared-файлов, если это не обязательно.

---

# 20. Запрещённый подход

Не запускать пять агентов одновременно от пустого репозитория.

Неправильно:

```text
Agent A проектирует models
Agent B тоже проектирует models
Agent C создаёт собственный TaskStatus
Agent D создаёт другую архитектуру services
```

Это приводит к несовместимым реализациям.

---

# 21. Правильный подход

```text
1. Agent 1 создаёт архитектуру.
2. Architecture commit фиксируется.
3. Agents 2–4 получают один и тот же commit.
4. Agents 2–4 работают в независимых областях.
5. Ветки объединяются.
6. Agent 5 тестирует итоговую систему.
7. Agent 5 исправляет только реальные integration issues.
```

---

# 22. Definition of Done для каждого агента

Агент не должен писать только код.

Перед завершением он обязан:

1. Запустить formatter.
2. Запустить linter.
3. Запустить type checks, если настроены.
4. Запустить unit tests своей области.
5. Запустить relevant integration tests.
6. Проверить отсутствие секретов.
7. Проверить, что приложение импортируется без ошибок.
8. Кратко описать сделанные изменения.
9. Указать известные ограничения, если они остались.
10. Сделать логически цельный commit.

---

# 23. Общие требования к тестам

Рекомендуемый стек:

```text
pytest
pytest-asyncio
```

Тесты не должны зависеть от реального Telegram Bot API там, где это можно замокать.

Для integration tests допускается отдельная PostgreSQL test database.

Особое внимание тестам:

- permissions;
- concurrency;
- recurrence;
- scheduled notifications;
- status transitions;
- invalid dates;
- multiple assignees.

---

# 24. Код-стиль

Предпочтения:

```text
Python 3.12+
async/await
type hints
SQLAlchemy 2.x async
Pydantic
aiogram 3.x
```

Не использовать:

- глобальные mutable singletons для бизнес-состояния;
- raw SQL без необходимости;
- timezone-naive datetime для бизнес-логики;
- handlers по несколько сотен строк;
- repository logic внутри Telegram handlers.

---

# 25. Важное правило при конфликте требований

Приоритет:

```text
1. Основное техническое задание
2. AGENTS.md
3. Существующие архитектурные контракты
4. Локальное решение отдельного агента
```

Если агент обнаруживает неясность, он должен выбрать вариант, который:

- минимально меняет существующую архитектуру;
- соответствует уже реализованным контрактам;
- не добавляет функциональность, которой нет в ТЗ.

---

# 26. Что НЕ входит в MVP

Агенты не должны самостоятельно добавлять:

- AI/LLM;
- web dashboard;
- Telegram Mini App;
- Google Calendar;
- Notion;
- Jira;
- статистику;
- leaderboard;
- полнотекстовый поиск;
- attachments;
- comments subsystem;
- natural-language date parser;
- multi-group support.

Даже если агент считает функцию полезной, она не должна попадать в MVP без отдельного изменения ТЗ.

---

# 27. Итоговое распределение ответственности

| Область | Ответственный |
|---|---|
| Архитектура | Agent 1 |
| Docker | Agent 1 |
| PostgreSQL models | Agent 1 |
| Alembic | Agent 1 |
| Domain contracts | Agent 1 |
| Telegram handlers | Agent 2 |
| FSM | Agent 2 |
| Inline UI | Agent 2 |
| Lists/archive/admin UI | Agent 2 |
| Notifications | Agent 3 |
| Scheduler | Agent 3 |
| Daily digest | Agent 3 |
| Overdue reminders | Agent 3 |
| Task state machine | Agent 4 |
| Permissions | Agent 4 |
| Recurrence | Agent 4 |
| Task history | Agent 4 |
| Integration | Agent 5 |
| E2E tests | Agent 5 |
| Race-condition review | Agent 5 |
| Final fixes | Agent 5 |

---

# 28. Короткая инструкция оркестратору

Если разработка запускается через управляющего агента Codex, использовать следующий порядок:

```text
STEP 1
Запусти Agent 1.
Не запускай других агентов до завершения foundation.

STEP 2
Зафиксируй foundation commit.

STEP 3
От foundation commit параллельно запусти:
- Agent 2
- Agent 3
- Agent 4

STEP 4
После завершения всех трёх агентов объедини изменения.

STEP 5
Разреши merge conflicts с приоритетом:
domain contracts > service contracts > local implementation.

STEP 6
Запусти Agent 5 на объединённой версии.

STEP 7
Agent 5 запускает полный test suite, Docker, migrations и e2e.

STEP 8
Исправь найденные Agent 5 проблемы.

STEP 9
Считать MVP готовым только после прохождения Definition of Done.
```

---

# 29. Основной принцип

Каждый агент должен решать одну ограниченную часть проекта.

Необходимо избегать ситуации, когда каждый агент «делает бота целиком».

Главное разделение:

```text
Architecture
Telegram Interface
Scheduling
Business Logic
Integration
```

Именно эти пять областей являются границами ответственности проекта.
