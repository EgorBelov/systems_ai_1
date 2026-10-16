const form = document.getElementById("auth-form");
const errorBox = document.getElementById("auth-error");

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function extractDetail(data) {
  if (!data || !data.detail) return null;
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail) && data.detail.length) {
    const first = data.detail[0];
    if (first && typeof first.msg === "string") return first.msg;
  }
  return "Проверьте введённые данные";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  showError("");

  const email = form.email.value.trim();
  const password = form.password.value;
  const endpoint = form.dataset.endpoint;
  const redirect = form.dataset.redirect || "/";
  const submit = form.querySelector("button[type=submit]");

  submit.disabled = true;
  try {
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });

    if (!res.ok) {
      let message = `Ошибка ${res.status}`;
      try {
        message = extractDetail(await res.json()) || message;
      } catch (_) {}
      showError(message);
      return;
    }

    window.location.href = redirect;
  } catch (err) {
    showError("Не удалось связаться с сервером");
  } finally {
    submit.disabled = false;
  }
});

fetch("/api/auth/me")
  .then((res) => {
    if (res.ok) window.location.href = "/";
  })
  .catch(() => {});
