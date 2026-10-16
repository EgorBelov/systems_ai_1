# Todo — FastAPI + Supabase, деплой на Vercel

Список задач с регистрацией и авторизацией. Бэкенд на FastAPI, страницы — статический HTML,
который раздаёт тот же FastAPI. Данные — в Postgres (Supabase), сессии — на сервере.

## Что внутри

```
.
├── api/
│   └── index.py        # FastAPI: auth + todos + раздача public/
├── public/             # статические страницы и ассеты
│   ├── index.html      # список задач (требует входа)
│   ├── login.html
│   ├── register.html
│   ├── style.css
│   ├── app.js
│   └── auth.js
├── requirements.txt
├── vercel.json
└── .env.example
```

## Модель авторизации

* Пароли хешируются Argon2 (`argon2-cffi`), в БД хранится только хеш.
* При входе создаётся строка в таблице `sessions` со сроком жизни 30 дней.
* В браузер кладётся случайный токен в `httpOnly` cookie; в БД хранится его SHA-256,
  поэтому утечка дампы сессий не даёт войти под пользователем.
* Задачи привязаны к `user_id` — каждый видит только свои.

Таблицы (`users`, `sessions`, `todos`) создаются автоматически при старте приложения.

## Локальный запуск

```bash
cp .env.example .env        # либо оставьте DATABASE_URL пустым для SQLite
# для локального http отключите secure-cookie:
#   COOKIE_SECURE=0
pip install -r requirements.txt
uvicorn api.index:app --reload
```

Открыть http://127.0.0.1:8000

Если `DATABASE_URL` не задан, приложение использует локальный SQLite (`todos.db`) —
удобно для разработки. На Vercel задайте `DATABASE_URL` на Supabase.

## Деплой на Vercel

1. Создайте проект в Supabase, возьмите строку подключения из
   **Project Settings → Database → Connection string → URI**.
   Для serverless берите **Connection Pooling → Transaction** (порт `6543`).
2. Импортируйте репозиторий в Vercel.
3. Добавьте переменные окружения (**Settings → Environment Variables**):

   | Переменная      | Значение                                  |
   | --------------- | ----------------------------------------- |
   | `DATABASE_URL`  | строка подключения Supabase (pooler, 6543)|
   | `COOKIE_SECURE` | `1`                                        |

4. Deploy. Vercel выполнит `api/index.py` как ASGI-функцию (`@vercel/python`),
   а `public/**` попадёт в бандл через `includeFiles` — статику раздаёт FastAPI.

`vercel.json` направляет все пути на функцию:

```json
{ "routes": [{ "src": "/(.*)", "dest": "api/index.py" }] }
```

## API

Аутентификация (`POST`):

| Метод | Путь                 | Тело / Ответ                          |
| ----- | -------------------- | ------------------------------------- |
| POST  | `/api/auth/register` | `{email, password}` → пользователь + cookie |
| POST  | `/api/auth/login`    | `{email, password}` → пользователь + cookie |
| POST  | `/api/auth/logout`   | закрывает сессию и чистит cookie      |
| GET   | `/api/auth/me`       | текущий пользователь или `401`        |

Задачи (нужен cookie):

| Метод  | Путь              | Описание                     |
| ------ | ----------------- | ---------------------------- |
| GET    | `/api/todos`      | список задач пользователя    |
| POST   | `/api/todos`      | создать `{title}`            |
| PATCH  | `/api/todos/{id}` | обновить `title` / `done`    |
| DELETE | `/api/todos/{id}` | удалить задачу               |

## Примечания

* Cookie ставится с `SameSite=Lax` + `Secure` (на Vercel) и `httpOnly`.
* Для запросов с другого домена понадобился бы CORS — здесь всё с одного origin,
  поэтому он не нужен.
