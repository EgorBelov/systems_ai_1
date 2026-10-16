const API = "/api/todos";

const form = document.getElementById("todo-form");
const input = document.getElementById("todo-input");
const list = document.getElementById("todo-list");
const empty = document.getElementById("empty");
const errorBox = document.getElementById("error");
const counter = document.getElementById("counter");
const who = document.getElementById("who");
const logout = document.getElementById("logout");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function goToLogin() {
  window.location.href = "/login.html";
}

async function request(url, options) {
  const res = await fetch(url, options);
  if (res.status === 401) {
    goToLogin();
    throw new Error("unauthorized");
  }
  if (!res.ok) {
    let detail = `Ошибка ${res.status}`;
    try {
      const data = await res.json();
      if (data && data.detail) {
        detail = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      }
    } catch (_) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

function render(todos) {
  list.innerHTML = "";

  for (const todo of todos) {
    const li = document.createElement("li");
    li.className = "todo" + (todo.done ? " todo--done" : "");

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "todo__checkbox";
    checkbox.checked = todo.done;
    checkbox.addEventListener("change", async () => {
      try {
        await request(`${API}/${todo.id}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ done: checkbox.checked }),
        });
        await load();
      } catch (err) {
        if (err.message !== "unauthorized") {
          checkbox.checked = !checkbox.checked;
          showError(err.message);
        }
      }
    });

    const title = document.createElement("span");
    title.className = "todo__title";
    title.textContent = todo.title;

    const del = document.createElement("button");
    del.className = "todo__delete";
    del.type = "button";
    del.title = "Удалить";
    del.textContent = "\u00d7";
    del.addEventListener("click", async () => {
      try {
        await request(`${API}/${todo.id}`, { method: "DELETE" });
        await load();
      } catch (err) {
        if (err.message !== "unauthorized") showError(err.message);
      }
    });

    li.append(checkbox, title, del);
    list.append(li);
  }

  const done = todos.filter((t) => t.done).length;
  counter.textContent = `Всего: ${todos.length} · Выполнено: ${done}`;
  empty.hidden = todos.length > 0;
}

async function load() {
  try {
    const todos = await request(API);
    render(todos);
    showError("");
  } catch (err) {
    if (err.message !== "unauthorized") showError(err.message);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const title = input.value.trim();
  if (!title) return;
  try {
    await request(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    });
    input.value = "";
    await load();
  } catch (err) {
    if (err.message !== "unauthorized") showError(err.message);
  }
});

logout.addEventListener("click", async () => {
  try {
    await fetch("/api/auth/logout", { method: "POST" });
  } catch (_) {}
  goToLogin();
});

async function init() {
  try {
    const res = await fetch("/api/auth/me");
    if (!res.ok) {
      goToLogin();
      return;
    }
    const user = await res.json();
    who.textContent = user.email;
  } catch (_) {
    goToLogin();
    return;
  }
  await load();
}

init();
