(() => {
  "use strict";

  const tg = window.Telegram?.WebApp;
  const state = {
    // Telegram may populate initData as the WebView finishes initializing.
    // Refresh it after tg.ready() immediately before the first auth decision.
    initData: "",
    profile: null,
    season: null,
    events: [],
    planned: [],
    filter: "all",
    busy: false,
    currentEventId: null,
    currentScreen: "home"
  };

  const floors = [
    { id: 1, code: "INITIATION", name: "Ініціація", desc: "Точка входу в CHRONOS. Тут починається особистий профіль, базовий аватар і знайомство із системою.", rule: "ДОСТУП: ПІСЛЯ СТАРТУ СЕЗОНУ", accent: "" },
    { id: 2, code: "OPERATIONS", name: "Операції", desc: "Запрошення на вечори, календар, реєстрації, присутність і персональна активність.", rule: "ВІДКРИТТЯ: ПЕРША РЕЄСТРАЦІЯ", accent: "" },
    { id: 3, code: "IDENTITY CENTER", name: "Центр ідентичності", desc: "Аватар, рамки, ефекти, звання та рівень оператора.", rule: "ВІДКРИТТЯ: ПЕРШИЙ ПІДТВЕРДЖЕНИЙ ВЕЧІР", accent: "" },
    { id: 4, code: "COLLECTION VAULT", name: "Сховище колекцій", desc: "Досягнення, предмети та колекція нагород сезону.", rule: "ВІДКРИТТЯ: ПЕРШЕ ДОСЯГНЕННЯ", accent: "" },
    { id: 5, code: "SIMULATION ROOM", name: "Симуляційна кімната", desc: "Мініігри CODE BREAKER та MEMORY. Тренуй уважність і збирай досвід.", rule: "ВІДКРИТТЯ: ПЕРША ЗІГРАНА МІНІГРА", accent: "" },
    { id: 6, code: "INITIALIZATION HUB", name: "Вузол ініціалізації", desc: "Перша контрольна точка сезону — 25% глобальної синхронізації та Кубок ініціалізації.", rule: "ВІДКРИТТЯ: 25% SYNC", accent: "final" },
    { id: 7, code: "PREDICTION EXCHANGE", name: "Біржа прогнозів", desc: "Ринки TOP 1, TOP 2 та TOP 3. Прогнози працюють окремо від спортивного рейтингу.", rule: "ПРОГНОЗИ: ЗА ПРАВИЛАМИ ДОСТУПУ", accent: "prediction" },
    { id: 8, code: "OVERDRIVE LAB", name: "Лабораторія Overdrive", desc: "Контрольна точка 75% синхронізації та проходження другого проміжного фіналу.", rule: "ВІДКРИТТЯ: 75% + ФІНАЛ №2", accent: "final" },
    { id: 9, code: "LEGACY HALL", name: "Зала спадщини", desc: "Результати трьох проміжних фіналів, історія сезону та відзнака CHRONOS LEGACY.", rule: "ВІДКРИТТЯ: 3 ПРОМІЖНІ ФІНАЛИ", accent: "final" },
    { id: 10, code: "CHRONOS CORE", name: "Ядро CHRONOS", desc: "Фінальна глава сезону. Main Final, чемпіони та завершення хронології.", rule: "ВІДКРИТТЯ: 100% + 3 ФІНАЛИ", accent: "final" }
  ];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[char]));

  function setConnection(online, label) {
    const node = $("#connection-state");
    node.classList.toggle("offline", !online);
    node.innerHTML = "<i></i> " + escapeHtml(label || (online ? "ONLINE" : "OFFLINE"));
  }

  function toast(message) {
    const node = $("#toast");
    node.textContent = message;
    node.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => node.classList.remove("show"), 2600);
  }

  function apiHeaders(json = false) {
    const headers = {};
    if (state.initData) headers.Authorization = "tma " + state.initData;
    if (json) headers["Content-Type"] = "application/json";
    return headers;
  }

  async function api(path, options = {}) {
    if (!state.initData) throw new Error("Відкрий Mini App з Telegram, щоб підтвердити акаунт.");
    const response = await fetch("/api/chronos" + path, {
      method: options.method || "GET",
      headers: apiHeaders(Boolean(options.body)),
      body: options.body ? JSON.stringify(options.body) : undefined,
      cache: "no-store"
    });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(data.message || ({
        401: "Telegram-сесія застаріла. Закрий Mini App і відкрий знову.",
        403: "Для цього акаунта доступ обмежено.",
        503: "Сезон ще не підготовлений на сервері."
      }[response.status] || "Не вдалося виконати запит."));
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function formatDate(date, time) {
    if (!date) return "ДАТУ ЩЕ НЕ ВИЗНАЧЕНО";
    const parsed = new Date(date + "T00:00:00");
    if (Number.isNaN(parsed.getTime())) return date;
    const day = parsed.toLocaleDateString("uk-UA", { day: "2-digit", month: "short" }).replace(".", "").toUpperCase();
    const year = parsed.getFullYear();
    return day + " " + year + (time ? " · " + time : "");
  }

  function splitDate(date) {
    if (!date) return ["—", "TBA"];
    const parsed = new Date(date + "T00:00:00");
    if (Number.isNaN(parsed.getTime())) return ["—", "TBA"];
    return [
      parsed.toLocaleDateString("uk-UA", { day: "2-digit" }),
      parsed.toLocaleDateString("uk-UA", { month: "short" }).replace(".", "").toUpperCase()
    ];
  }

  function renderRoom() {
    const title = $("#hall-session-title");
    const note = $("#hall-session-note");
    if (!title || !note) return;
    const live = state.events[0];
    const planned = state.planned[0];
    if (live) {
      title.textContent = live.title || "Поточний вечір KMC";
      note.textContent = "Подія відкрита · " + (Number(live.active_count) || 0) + " учасників у реєстрації.";
      const button = document.querySelector("#screen-room [data-nav='events']");
      if (button) {
        button.dataset.eventId = String(live.event_id);
        button.dataset.nav = "";
        button.textContent = "ПЕРЕГЛЯНУТИ СКЛАД ↗";
      }
      return;
    }
    if (planned) {
      title.textContent = planned.title || "Наступний вечір";
      note.textContent = planned.planned_date ? "Заплановано на " + formatDate(planned.planned_date) + ". Реєстрація відкривається через Telegram-бот." : "Подію заплановано. Дату та реєстрацію організатор повідомить у Telegram.";
    } else {
      title.textContent = "Зала очікує на вечір";
      note.textContent = "Коли організатор відкриє подію, тут з'явиться її актуальний стан.";
    }
    const button = document.querySelector("#screen-room [data-event-id]");
    if (button) {
      button.removeAttribute("data-event-id");
      button.dataset.nav = "events";
      button.textContent = "ПЕРЕЙТИ ДО ПОДІЙ ↗";
    }
  }

  function showScreen(name) {
    state.currentScreen = name;
    $(".screen").forEach(el => el.classList.toggle("active", el.dataset.screen === name));
    $(".nav-item").forEach(el => el.classList.toggle("active", el.dataset.nav === name));
    if (name === "room") renderRoom();
    if (tg?.HapticFeedback) tg.HapticFeedback.selectionChanged();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function currentProfileName() {
    return state.profile?.display_name || "Гість системи";
  }

  function renderProfile() {
    const name = currentProfileName();
    $("#home-name").textContent = name;
    $("#profile-name").textContent = name;
    $("#avatar-initial").textContent = name.trim().slice(0, 1).toUpperCase() || "?";
    const complete = Boolean(state.profile?.profile_complete);
    $("#home-profile-note").textContent = complete ? "Профіль синхронізовано з KMC" : "Потрібно завершити /start у боті";
    $("#profile-telegram").textContent = complete ? "KMC PLAYER REGISTRY" : "PROFILE NOT LINKED";
    $("#profile-role").textContent = state.profile?.role === "admin" ? "ADMIN" : complete ? "INITIATE" : "PENDING";
  }

  function renderHomeEvent() {
    const live = state.events[0];
    const planned = state.planned[0];
    const container = $("#home-event");

    if (live) {
      container.innerHTML = `
        <div class="event-tag">LIVE OPERATION</div>
        <h3>${escapeHtml(live.title)}</h3>
        <p>${escapeHtml(formatDate(live.event_date, live.event_time))} &nbsp;·&nbsp; ${Number(live.active_count) || 0} УЧАСНИКІВ</p>
        <button class="event-open" data-event-id="${live.event_id}" aria-label="Відкрити подію">↗</button>`;
      return;
    }
    if (planned) {
      container.innerHTML = `
        <div class="event-tag" style="color:var(--violet)">NEXT IN CHRONOLOGY</div>
        <h3>${escapeHtml(planned.title)}</h3>
        <p>${escapeHtml(planned.planned_date ? formatDate(planned.planned_date) : "ДАТУ ЩЕ НЕ ВИЗНАЧЕНО")} &nbsp;·&nbsp; СКОРО</p>
        <button class="event-open" data-nav="events" aria-label="Відкрити календар">↗</button>`;
      return;
    }
    container.innerHTML = `
      <div class="event-tag">NO ACTIVE OPERATION</div>
      <h3>Хронологія очікує</h3>
      <p>Коли бот створить CHRONOS-подію, вона автоматично з'явиться тут.</p>`;
  }

  function eventCard(event, planned = false) {
    const date = splitDate(planned ? event.planned_date : event.event_date);
    const code = planned ? event.slot_code : (event.slot_code || ("EVENT " + event.event_id));
    const subtitle = planned
      ? (event.planned_date ? formatDate(event.planned_date) : "ДАТУ НЕ ВИЗНАЧЕНО") + " · СКОРО"
      : formatDate(event.event_date, event.event_time) + " · " + (Number(event.active_count) || 0) + " ГРАВЦІВ";
    return `
      <article class="event-card ${planned ? "planned" : ""}">
        <div class="event-date-box"><b>${escapeHtml(date[0])}</b><small>${escapeHtml(date[1])}</small></div>
        <div class="event-copy">
          <small>${escapeHtml(code)} · ${planned ? "PLANNED" : "LIVE"}</small>
          <h3>${escapeHtml(event.title)}</h3>
          <p>${escapeHtml(subtitle)}</p>
        </div>
        ${planned
          ? '<button class="event-action" data-nav="tower" aria-label="Переглянути поверхи">↗</button>'
          : `<button class="event-action" data-event-id="${event.event_id}" aria-label="Деталі події">↗</button>`}
      </article>`;
  }

  function renderEvents() {
    const filteredLive = state.filter === "planned" ? [] : state.events;
    const filteredPlanned = state.filter === "live" ? [] : state.planned;
    const allCount = state.events.length + state.planned.length;
    $("#event-count").textContent = String(allCount);
    const pieces = [
      ...filteredLive.map(event => eventCard(event, false)),
      ...filteredPlanned.map(event => eventCard(event, true))
    ];
    $("#events-list").innerHTML = pieces.length
      ? pieces.join("")
      : '<div class="empty-state"><span class="empty-symbol">⌁</span><b>Поки що порожньо</b><small>Нові CHRONOS-події з’являться після створення в боті.</small></div>';
    $$(".filter-tab").forEach(el => el.classList.toggle("active", el.dataset.filter === state.filter));
  }

  function renderTower() {
    $("#tower-floors").innerHTML = floors.map(floor => `
      <button class="floor-card ${floor.accent}" data-floor-id="${floor.id}">
        <span class="floor-number">${String(floor.id).padStart(2, "0")}</span>
        <span class="floor-info"><strong>${escapeHtml(floor.name)}</strong><small>${escapeHtml(floor.code)} · ${escapeHtml(floor.rule)}</small></span>
        <span class="floor-arrow">›</span>
      </button>`).join("");
  }

  async function openEvent(eventId) {
    state.currentEventId = Number(eventId);
    openModal("EVENT DETAIL", '<div class="loading-line"></div><div class="loading-line short"></div>');
    try {
      const data = await api("/events/" + encodeURIComponent(eventId));
      const event = data.event;
      const registered = Boolean(event.is_registered);
      const seasonActive = state.season?.status === "active";
      const profileComplete = Boolean(state.profile?.profile_complete);
      const canRegister = seasonActive && profileComplete && !registered;

      const roster = (data.roster || []).map((player, index) => `
        <div class="roster-row"><span class="roster-num">${String(index + 1).padStart(2, "0")}</span><span class="roster-name">${escapeHtml(player.display_name)}</span></div>`).join("");

      let lockNote = "";
      if (!profileComplete) lockNote = "Спочатку заверши /start у Telegram-боті та вкажи ігровий нік.";
      else if (!seasonActive) lockNote = "Реєстрація відкриється після офіційного запуску сезону.";
      else if (registered) lockNote = "Ти вже є у списку учасників цього вечора.";

      $("#modal-content").innerHTML = `
        <div class="event-tag">CHRONOS OPERATION #${event.event_id}</div>
        <h2 class="modal-title" id="modal-title">${escapeHtml(event.title)}</h2>
        <div class="modal-meta"><span>◷ ${escapeHtml(formatDate(event.event_date, event.event_time))}</span><span>◉ ${Number(event.active_count) || 0} ГРАВЦІВ</span></div>
        <p class="modal-copy">Реєстрація синхронізується з основним Telegram-ботом KMC. Список показує всіх зареєстрованих на вечір — кількість учасників не обмежена десятьма.</p>
        <div class="roster-head"><span>ОПЕРАТИВНИЙ СКЛАД</span><span>${(data.roster || []).length} / ∞</span></div>
        <div class="roster-list">${roster || '<div class="modal-copy">Поки ніхто не зареєструвався.</div>'}</div>
        <button class="modal-action" id="register-button" ${canRegister ? "" : "disabled"}>${registered ? "✓ ТИ ВЖЕ В СПИСКУ" : !seasonActive ? "РЕЄСТРАЦІЯ ЩЕ ЗАКРИТА" : !profileComplete ? "СПЕРШУ ЗАВЕРШИ ПРОФІЛЬ" : "ПІДТВЕРДИТИ РЕЄСТРАЦІЮ"}</button>
        ${lockNote ? '<p class="modal-copy">' + escapeHtml(lockNote) + '</p>' : ""}`;
      $("#register-button")?.addEventListener("click", () => registerForEvent(event.event_id));
    } catch (error) {
      $("#modal-content").innerHTML = '<h2 class="modal-title" id="modal-title">Не вдалося завантажити</h2><p class="modal-copy">' + escapeHtml(error.message) + '</p>';
    }
  }

  async function registerForEvent(eventId) {
    const button = $("#register-button");
    if (button) { button.disabled = true; button.textContent = "ОБРОБКА ЗАПИТУ..."; }
    try {
      await api("/events/" + encodeURIComponent(eventId) + "/register", {
        method: "POST",
        body: { comment: null }
      });
      toast("Реєстрацію підтверджено");
      if (tg?.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
      await refreshData();
      await openEvent(eventId);
    } catch (error) {
      if (button) { button.disabled = false; button.textContent = "ПОВТОРИТИ"; }
      toast(error.message);
      if (error.status === 401) setConnection(false, "SESSION EXPIRED");
    }
  }

  function openFloor(floorId) {
    const floor = floors.find(item => item.id === Number(floorId));
    if (!floor) return;
    openModal("TOWER / FLOOR " + String(floor.id).padStart(2, "0"), `
      <div class="floor-modal-code">${escapeHtml(floor.code)}</div>
      <h2 class="modal-title" id="modal-title">${escapeHtml(floor.name)}</h2>
      <p class="modal-copy">${escapeHtml(floor.desc)}</p>
      <div class="notice-card"><span class="notice-mark">⌁</span><div><b>Умова доступу</b><p>${escapeHtml(floor.rule)}. Поверх можна переглянути вже зараз; функціонал активується окремо після виконання умови.</p></div></div>
      <button class="modal-action" id="floor-close">ЗРОЗУМІЛО</button>`);
    $("#floor-close")?.addEventListener("click", closeModal);
  }

  function openModal(kicker, content) {
    $("#modal-kicker").textContent = kicker;
    $("#modal-content").innerHTML = content;
    $("#modal-backdrop").classList.add("open");
    $("#modal-backdrop").setAttribute("aria-hidden", "false");
    if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred("light");
  }

  function closeModal() {
    $("#modal-backdrop").classList.remove("open");
    $("#modal-backdrop").setAttribute("aria-hidden", "true");
  }

  function showSoonScreen() {
    document.querySelector("#soon-screen").hidden = false;
    document.querySelector("#app-shell").hidden = true;
  }

  function showFullApp() {
    document.querySelector("#soon-screen").hidden = true;
    document.querySelector("#app-shell").hidden = false;
  }

  async function refreshData() {
    if (state.busy) return;
    state.busy = true;
    setConnection(false, "SYNCING");
    try {
      const profile = await api("/me");
      state.profile = profile;
      showFullApp();
      const calendar = await api("/events");
      state.profile = profile;
      state.season = calendar.season;
      state.events = calendar.events || [];
      state.planned = calendar.planned_slots || [];
      renderProfile();
      renderHomeEvent();
      renderRoom();
      renderEvents();
      $("#season-state").textContent = state.season?.status === "active"
        ? "SEASON ACTIVE"
        : state.season?.status === "paused" ? "SEASON PAUSED" : "SEASON PREVIEW";
      setConnection(true, "SYNCED");
    } catch (error) {
      setConnection(false, "OFFLINE");
      if (!state.profile) {
        showSoonScreen();
        return;
      }
      $("#home-event").innerHTML = `
        <div class="event-tag">CONNECTION ERROR</div>
        <h3>Систему не синхронізовано</h3>
        <p>${escapeHtml(error.message)}</p>`;
      $("#events-list").innerHTML = `
        <div class="empty-state"><span class="empty-symbol">⌁</span><b>Немає зв'язку з сервером</b><small>${escapeHtml(error.message)}</small></div>`;
      $("#season-state").textContent = "SYNC UNAVAILABLE";
    } finally {
      state.busy = false;
    }
  }

  document.addEventListener("click", event => {
    const nav = event.target.closest("[data-nav]");
    if (nav) {
      event.preventDefault();
      showScreen(nav.dataset.nav);
      closeModal();
      return;
    }
    const eventButton = event.target.closest("[data-event-id]");
    if (eventButton) {
      openEvent(eventButton.dataset.eventId);
      return;
    }
    const floorButton = event.target.closest("[data-floor-id]");
    if (floorButton) {
      openFloor(floorButton.dataset.floorId);
      return;
    }
    const filterButton = event.target.closest("[data-filter]");
    if (filterButton) {
      state.filter = filterButton.dataset.filter;
      renderEvents();
    }
  });

  $("#refresh-button").addEventListener("click", refreshData);
  $("#modal-close").addEventListener("click", closeModal);
  $("#modal-backdrop").addEventListener("click", event => {
    if (event.target === $("#modal-backdrop")) closeModal();
  });

  renderTower();
  renderProfile();

  if (tg) {
    tg.ready();
    tg.expand();
    try { tg.setHeaderColor("#080d12"); tg.setBackgroundColor("#080d12"); } catch (_) {}
    if (tg.disableVerticalSwipes) tg.disableVerticalSwipes();
  }

  state.initData = tg?.initData || "";
  if (!state.initData) {
    showSoonScreen();
  } else {
    refreshData();
  }
})();
