const get = (id) => document.getElementById(id);
const form = get("form");
const urls = get("urls");
const count = get("count");
const submit = get("submit");
const clear = get("clear");
const error = get("error");
const status = get("status");
const cards = get("cards");
const copyAll = get("copy-all");
const template = get("result-card");
const theme = get("theme");
const maxLinks = Number(form.dataset.maxLinks);
const copyTimers = new WeakMap();

const lines = () => urls.value.split(/\r?\n/).map((line) => line.trim()).filter(Boolean);

function updateCount() {
  const total = lines().length;
  count.textContent = `${total} / ${maxLinks} links`;
  count.classList.toggle("error", total > maxLinks);
}

async function copy(text, button, label) {
  clearTimeout(copyTimers.get(button));
  let message;
  try {
    await navigator.clipboard.writeText(text);
    message = "Copied!";
  } catch {
    message = "Copy failed";
  }
  button.textContent = message;
  get("copy-status").textContent = message === "Copied!"
    ? "Transcript text copied."
    : "Clipboard access failed. Select the transcript text to copy it manually.";
  copyTimers.set(button, setTimeout(() => { button.textContent = label; }, 2000));
}

function render(items) {
  const successful = items.filter((item) => !item.error);
  cards.replaceChildren();
  copyAll.disabled = successful.length === 0;
  copyAll.onclick = () => copy(
    successful.map(({ url, text }) => `${url}\n\n${text}`).join("\n\n────────\n\n"),
    copyAll,
    "Copy All",
  );

  for (const item of items) {
    const card = template.content.cloneNode(true);
    const heading = card.querySelector(".video-url");
    heading.textContent = item.url || "Invalid URL";
    if (!item.error) {
      const link = document.createElement("a");
      link.href = `https://www.youtube.com/watch?v=${encodeURIComponent(item.video_id)}`;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = item.url;
      heading.replaceChildren(link);
    }

    const meta = card.querySelector(".meta");
    meta.textContent = item.video_id ? `Video ID: ${item.video_id}` : "";
    if (item.language) meta.textContent += ` · ${item.language}`;
    meta.hidden = !meta.textContent;

    const caption = card.querySelector(".caption");
    caption.textContent = item.error || item.text;
    caption.classList.toggle("error", Boolean(item.error));
    const button = card.querySelector(".copy");
    button.hidden = Boolean(item.error);
    button.addEventListener("click", () => copy(item.text, button, "Copy"));
    cards.append(card);
  }
  return successful.length;
}

function setLoading(loading) {
  form.setAttribute("aria-busy", String(loading));
  urls.readOnly = loading;
  submit.disabled = clear.disabled = loading;
  get("submit-label").textContent = loading ? "Fetching…" : "Get Transcripts";
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const urlsToFetch = lines();
  if (!urlsToFetch.length || urlsToFetch.length > maxLinks) {
    error.textContent = `Enter between 1 and ${maxLinks} YouTube URLs.`;
    urls.focus();
    return;
  }

  error.textContent = "";
  render([]);
  setLoading(true);
  status.textContent = "Fetching captions…";
  try {
    const response = await fetch("/api/transcripts", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ urls: urlsToFetch }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !Array.isArray(data.results)) {
      error.textContent = data.error || "The server could not complete the request. Try again.";
      status.textContent = "";
      return;
    }
    const found = render(data.results);
    status.textContent = `${found} of ${urlsToFetch.length} retrieved.`;
  } catch {
    error.textContent = "Could not reach the server. Check your connection and try again.";
    status.textContent = "";
  } finally {
    setLoading(false);
  }
});

urls.addEventListener("input", () => {
  updateCount();
  error.textContent = "";
});
clear.addEventListener("click", () => {
  form.reset();
  updateCount();
  error.textContent = "";
  get("copy-status").textContent = "";
  status.textContent = "Your transcripts will appear here.";
  render([]);
  urls.focus();
});

function applyTheme(dark) {
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  theme.setAttribute("aria-pressed", String(dark));
  theme.textContent = dark ? "☀" : "☾";
}
let preference;
try { preference = localStorage.getItem("cue-theme"); } catch {}
applyTheme(preference ? preference === "dark" : matchMedia("(prefers-color-scheme: dark)").matches);
theme.addEventListener("click", () => {
  const dark = theme.getAttribute("aria-pressed") !== "true";
  applyTheme(dark);
  try { localStorage.setItem("cue-theme", dark ? "dark" : "light"); } catch {}
});
updateCount();
