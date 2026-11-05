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

  function resetAppScroll() {
    const reset = () => {
      const root = document.scrollingElement || document.documentElement;
      if (root) root.scrollTop = 0;
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
      const shell = $("#app-shell");
      const main = $("#app-main");
      if (shell) shell.scrollTop = 0;
      if (main) main.scrollTop = 0;
      resetAppScroll();
    };
    reset();
    if (typeof window.requestAnimationFrame === "function") {
      window.requestAnimationFrame(reset);
    }
    window.setTimeout(reset, 80);
  }

  function showScreen(name) {
    const nextScreen = $(".screen").find(el => el.dataset.screen === name);
    if (!nextScreen) {
      toast("Цей розділ зараз недоступний.");
      return false;
    }
    state.currentScreen = name;
    $(".screen").forEach(el => {
      const active = el === nextScreen;
      el.classList.toggle("active", active);
      el.setAttribute("aria-hidden", active ? "false" : "true");
    });
    const activeNav = name === "event-detail" ? "events" : name;
    $(".nav-item").forEach(el => {
      const active = el.dataset.nav === activeNav;
      el.classList.toggle("active", active);
      if (active) el.setAttribute("aria-current", "page");
      else el.removeAttribute("aria-current");
    });
    const shell = $("#app-shell");
    if (shell) shell.classList.toggle("detail-open", name === "event-detail");
    if (name === "room") renderRoom();
    try {
      if (tg?.HapticFeedback?.selectionChanged) tg.HapticFeedback.selectionChanged();
    } catch (_) {}
    resetAppScroll();
    return true;
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

  function renderTower() {
    $("#tower-floors").innerHTML = floors.map(floor => `
      <button class="floor-card ${floor.accent}" data-floor-id="${floor.id}">
        <span class="floor-number">${String(floor.id).padStart(2, "0")}</span>
        <span class="floor-info"><strong>${escapeHtml(floor.name)}</strong><small>${escapeHtml(floor.code)} · ${escapeHtml(floor.rule)}</small></span>
        <span class="floor-arrow">›</span>
      </button>`).join("");
  }

  function eventSlotType(event) {
    return event && event.slot_type ? event.slot_type : "regular";
  }

  function eventTitle(event, planned) {
    let title = String(event.title || "Вечір KMC");
    if (planned && eventSlotType(event) === "regular") {
      const match = title.match(/#\s*(\d+)/);
      title = match ? "Вечір #" + match[1] : "Вечір #" + String(event.sequence_no || "");
    }
    return title;
  }

  function eventArtwork(type) {
    if (type === "regular") {
      return '<div class="event-art event-art-room"><img src="assets/chronos-hall.svg" alt="" loading="lazy"></div>';
    }
    const main = type === "main_final";
    const color = main ? "#e9c77b" : "#b49aff";
    const shadow = main ? "rgba(233,199,123,.2)" : "rgba(180,154,255,.2)";
    return '<div class="event-art ' + (main ? "event-art-main" : "event-art-cup") + '">' +
      '<svg viewBox="0 0 120 120" aria-hidden="true">' +
      '<circle cx="60" cy="60" r="45" fill="none" stroke="' + color + '" stroke-opacity=".22" stroke-width="1"/>' +
      '<path d="M38 30h44v18c0 18-8 28-22 28S38 66 38 48V30Z" fill="' + color + '" fill-opacity=".13" stroke="' + color + '" stroke-width="2"/>' +
      '<path d="M38 38H24c0 19 8 27 22 27M82 38h14c0 19-8 27-22 27M60 76v17M43 96h34" fill="none" stroke="' + color + '" stroke-width="3" stroke-linecap="round"/>' +
      '<path d="M49 43h22M60 32v33" stroke="' + color + '" stroke-opacity=".55" stroke-width="1.5"/>' +
      '</svg><span>' + (main ? "GRAND FINAL" : "CHRONOS CUP") + '</span></div>';
  }

  function eventCard(event, planned) {
    const type = eventSlotType(event);
    const isFinal = type !== "regular";
    const title = escapeHtml(eventTitle(event, planned));
    const code = escapeHtml(event.slot_code || (event.event_id ? "EVENT " + event.event_id : ""));
    if (planned) {
      return '<article class="event-list-card planned-card ' + (isFinal ? "final-card" : "regular-card") + '">' +
        eventArtwork(type) +
        '<div class="event-card-copy">' +
          '<div class="event-card-title-row"><h3>' + title + '</h3><span class="event-status-pill soon">СКОРО</span></div>' +
          '<p class="event-card-kind">' + (isFinal ? (type === "main_final" ? "ГОЛОВНИЙ ФІНАЛ СЕЗОНУ" : "ПРОМІЖНИЙ ФІНАЛ") : "СЕЗОННИЙ ВЕЧІР") + '</p>' +
          '<span class="event-card-code">' + code + '</span>' +
        '</div></article>';
    }
    const count = Number(event.active_count) || 0;
    const date = escapeHtml(formatDate(event.event_date, event.event_time));
    const registered = Boolean(event.is_registered);
    const statusText = registered ? "ТИ ЗАРЕЄСТРОВАНИЙ" : (state.season && state.season.status === "active" ? "РЕЄСТРАЦІЯ ВІДКРИТА" : "РЕЄСТРАЦІЯ ЗАКРИТА");
    const statusClass = registered ? "joined" : (state.season && state.season.status === "active" ? "open" : "closed");
    const countText = String(count) + " УЧАСНИКІВ";
    return '<button type="button" class="event-list-card real-event-card ' + (isFinal ? "final-card" : "regular-card") + '" data-event-id="' + Number(event.event_id) + '">' +
      eventArtwork(type) +
      '<div class="event-card-copy">' +
        '<div class="event-card-title-row"><h3>' + title + '</h3><span class="event-chevron">›</span></div>' +
        '<div class="event-card-meta"><span class="meta-icon">▦</span><span>' + date + '</span></div>' +
        '<div class="event-card-meta"><span class="meta-icon">⌖</span><span>Театр комедії МО</span></div>' +
        '<div class="event-card-bottom"><span class="event-participant-count">◉ ' + countText + '</span><span class="event-status-pill ' + statusClass + '">' + statusText + '</span></div>' +
      '</div></button>';
  }

  function sortEventSlots(items) {
    return items.sort((a, b) => {
      const sa = Number(a.sequence_no) || 999;
      const sb = Number(b.sequence_no) || 999;
      if (sa !== sb) return sa - sb;
      return Number(Boolean(a.event_id)) - Number(Boolean(b.event_id));
    });
  }

  function renderEvents() {
    const events = (state.events || []).map(item => Object.assign({}, item, { planned: false }));
    const planned = (state.planned || []).map(item => Object.assign({}, item, { planned: true }));
    const all = sortEventSlots(events.concat(planned));
    const regular = all.filter(item => eventSlotType(item) === "regular");
    const finals = all.filter(item => eventSlotType(item) !== "regular");
    $("#event-count").textContent = String(all.length);
    $("#event-upcoming-count").textContent = String(regular.length);
    $("#event-finals-count").textContent = String(finals.length);

    const sections = [];
    if (state.filter !== "finals" && regular.length) {
      sections.push('<section class="event-group"><div class="event-group-heading"><div><span class="eyebrow">SEASON CALENDAR</span><h2>Найближчі вечори</h2></div><span>' + String(regular.length).padStart(2, "0") + '</span></div>' +
        '<div class="event-card-list">' + regular.map(item => eventCard(item, item.planned)).join("") + '</div></section>');
    }
    if (state.filter !== "upcoming" && finals.length) {
      sections.push('<section class="event-group"><div class="event-group-heading"><div><span class="eyebrow">SPECIAL OPERATIONS</span><h2>' + (state.filter === "finals" ? "Фінали сезону" : "Інші події сезону") + '</h2></div><span>' + String(finals.length).padStart(2, "0") + '</span></div>' +
        '<div class="event-card-list">' + finals.map(item => eventCard(item, item.planned)).join("") + '</div></section>');
    }
    $("#events-list").innerHTML = sections.length
      ? sections.join("")
      : '<div class="empty-state"><span class="empty-symbol">⌁</span><b>Подій у цьому розділі поки немає</b><small>Нові вечори та фінали з’являться тут після синхронізації з ботом KMC.</small></div>';
    $$(".filter-tab").forEach(el => el.classList.toggle("active", el.dataset.filter === state.filter));
  }

  function stageSeatMarkup(roster) {
    // Ten overlay positions correspond to the ten player chairs in chronos-hall.svg.
    // The host is a separate foreground figure, not a player seat.
    const positions = [
      ["50%", "24.7%"], ["69%", "30.6%"], ["80.5%", "47.5%"], ["71.5%", "67.4%"], ["59%", "72.5%"],
      ["41%", "72.5%"], ["28.5%", "67.4%"], ["19.5%", "47.5%"], ["31%", "30.6%"], ["50%", "76.2%"]
    ];
    return positions.map((point, index) => {
      const player = (roster || [])[index];
      const position = 'style="left:' + point[0] + ';top:' + point[1] + ';"';
      if (!player) {
        return '<div class="event-stage-seat empty" ' + position + '><span class="stage-empty-avatar">＋</span></div>';
      }
      const name = String(player.display_name || "Гравець");
      const initials = name.trim().split(/\s+/).slice(0, 2).map(part => part.charAt(0)).join("").toUpperCase() || "?";
      const base = String(player.avatar_base || "european_male").replace(/[^a-z0-9_-]/gi, "");
      return '<div class="event-stage-seat filled" ' + position + '>' +
        '<span class="stage-avatar avatar-' + base + '">' + escapeHtml(initials) + '</span>' +
        '<small>' + escapeHtml(name) + '</small>' +
      '</div>';
    }).join("");
  }

  function renderEventDetail(data) {
    const event = data.event || {};
    const roster = data.roster || [];
    const listEvent = (state.events || []).find(item => Number(item.event_id) === Number(event.event_id));
    const type = event.slot_type || eventSlotType(listEvent || {});
    const count = Math.max(Number(event.active_count) || 0, roster.length);
    const registered = Boolean(event.is_registered);
    const profileComplete = Boolean(state.profile && state.profile.profile_complete);
    const seasonActive = Boolean(state.season && state.season.status === "active");
    const canRegister = seasonActive && profileComplete && !registered;
    const statusText = registered ? "ТИ ЗАРЕЄСТРОВАНИЙ" : (seasonActive ? "РЕЄСТРАЦІЯ ВІДКРИТА" : "РЕЄСТРАЦІЯ ЗАКРИТА");
    const statusClass = registered ? "joined" : (seasonActive ? "open" : "closed");
    const formatText = type === "main_final" ? "Головний фінал сезону" : (type === "intermediate_final" ? "Проміжний фінал" : "Класичний KMC");
    const title = eventTitle(event, false);
    const dateText = event.event_date ? formatDate(event.event_date) : "Дата не визначена";
    const timeText = event.event_time || "—";
    const venueText = event.location || "Театр комедії МО";
    const playerMarkup = roster.slice(0, 10).map((player, index) => {
      const name = String(player.display_name || "Гравець");
      const initials = name.trim().split(/\s+/).slice(0, 2).map(part => part.charAt(0)).join("").toUpperCase() || "?";
      const base = String(player.avatar_base || "default").replace(/[^a-z0-9_-]/gi, "");
      return '<div class="event-seat occupied"><span class="seat-avatar avatar-' + base + '">' + escapeHtml(initials) + '</span><b>' + escapeHtml(name) + '</b><small>МІСЦЕ ' + String(index + 1).padStart(2, "0") + '</small></div>';
    }).join("");
    const emptyCount = Math.max(0, 10 - Math.min(10, roster.length));
    const emptyMarkup = Array.from({length: emptyCount}, (_, index) =>
      '<div class="event-seat empty-seat"><span class="seat-avatar">＋</span><b>Вільне місце</b><small>МІСЦЕ ' + String(Math.min(10, roster.length) + index + 1).padStart(2, "0") + '</small></div>'
    ).join("");
    const rotationPlayers = roster.slice(10);
    const rotationMarkup = rotationPlayers.length
      ? '<div class="event-rotation-panel">' +
          '<div class="event-rotation-heading"><span>ІНШІ ЗАРЕЄСТРОВАНІ</span><b>+' + rotationPlayers.length + '</b></div>' +
          '<p>Поза десятьма місцями за столом. Учасники можуть змінюватися між партіями вечора.</p>' +
          '<div class="event-rotation-list">' + rotationPlayers.map((player) => {
            const name = String(player.display_name || "Гравець");
            const initials = name.trim().split(/\s+/).slice(0, 2).map(part => part.charAt(0)).join("").toUpperCase() || "?";
            const base = String(player.avatar_base || "default").replace(/[^a-z0-9_-]/gi, "");
            return '<span class="rotation-player"><i class="rotation-avatar avatar-' + base + '">' + escapeHtml(initials) + '</i><b>' + escapeHtml(name) + '</b></span>';
          }).join("") + '</div></div>'
      : "";
    let helperText = "Список учасників синхронізується з Telegram-ботом KMC.";
    if (registered) helperText = "Твоя участь підтверджена. Склад вечора оновлюється з основної системи KMC.";
    else if (!profileComplete) helperText = "Щоб зареєструватися, спочатку заверши профіль через /start у боті KMC.";
    else if (!seasonActive) helperText = "Реєстрація стане доступною після офіційного запуску сезону.";

    const actionText = registered ? "СКАСУВАТИ РЕЄСТРАЦІЮ" : (!seasonActive ? "РЕЄСТРАЦІЯ ЗАКРИТА" : (!profileComplete ? "СПЕРШУ ЗАВЕРШИ ПРОФІЛЬ" : "ЗАРЕЄСТРУВАТИСЯ"));
    const actionClass = registered ? "event-action-cancel" : "event-action-register";
    const actionKind = registered ? "cancel" : "register";
    const actionDisabled = !registered && !canRegister ? "disabled" : "";

    $("#event-detail-content").innerHTML =
      '<div class="event-detail-topbar">' +
        '<button type="button" class="event-back-button" data-back-events aria-label="Назад до подій">←</button>' +
        '<div class="event-detail-heading"><small>CHRONOS / ПОДІЇ</small><h1>' + escapeHtml(title) + '</h1></div>' +
        '<span class="event-status-pill ' + statusClass + '">' + statusText + '</span>' +
      '</div>' +
      '<div class="event-detail-stage">' +
        '<img src="assets/chronos-hall.svg" alt="Ігрова зала KMC із круглим столом та десятьма місцями">' +
        '<div class="event-stage-shade"></div>' +
        '<div class="event-stage-seats">' + stageSeatMarkup(roster) + '</div>' +
        '<div class="event-stage-top"><span>◉ KMC PLAYER ARENA</span><b>CHRONOS · ' + (type === "regular" ? "REGULAR" : "FINAL") + '</b></div>' +
        '<div class="event-stage-bottom"><span>LIVE EVENT VIEW</span><strong>' + String(count).padStart(2, "0") + ' <small>ЗАРЕЄСТРОВАНО</small></strong><span class="stage-seat-capacity">10 МІСЦЬ В ОДНІЙ ГРІ</span></div>' +
      '</div>' +
      '<div class="event-facts">' +
        '<div class="event-fact"><span>▦</span><small>ДАТА</small><b>' + escapeHtml(dateText) + '</b></div>' +
        '<div class="event-fact"><span>◷</span><small>ЧАС</small><b>' + escapeHtml(timeText) + '</b></div>' +
        '<div class="event-fact"><span>⌖</span><small>МІСЦЕ</small><b>' + escapeHtml(venueText) + '</b></div>' +
      '</div>' +
      '<div class="event-detail-panel">' +
        '<div class="event-panel-heading"><div><span class="eyebrow">PLAYER ROSTER</span><h2>Місця за столом</h2></div><strong>' + Math.min(10, roster.length) + ' / 10</strong></div>' +
        '<div class="event-seat-progress">' + Array.from({length: 10}, (_, index) => '<i class="' + (index < Math.min(10, roster.length) ? "filled" : "") + '"></i>').join("") + '</div>' +
        '<div class="event-seat-grid">' + playerMarkup + emptyMarkup + '</div>' + rotationMarkup +
      '</div>' +
      '<div class="event-detail-facts">' +
        '<div class="event-info-row"><span class="event-info-icon">♛</span><div><small>ФОРМАТ</small><b>' + escapeHtml(formatText) + '</b></div></div>' +
        '<div class="event-info-row"><span class="event-info-icon">◉</span><div><small>СТАТУС</small><b>' + statusText + '</b></div><span class="event-status-dot ' + statusClass + '"></span></div>' +
      '</div>' +
      '<div class="event-detail-note"><span>i</span><p>' + escapeHtml(helperText) + '</p></div>' +
      '<button type="button" class="event-action-button ' + actionClass + '" id="event-action-button" data-event-action="' + actionKind + '" ' + actionDisabled + '>' + actionText + '</button>' +
      '<p class="event-sync-note">⌁ СПИСОК УЧАСНИКІВ СИНХРОНІЗОВАНО З БОТОМ KMC</p>';
  }

  async function openEvent(eventId) {
    state.currentEventId = Number(eventId);
    showScreen("event-detail");
    $("#event-detail-content").innerHTML = '<div class="detail-loading"><span class="pulse-dot"></span> ЗАВАНТАЖЕННЯ ПОДІЇ</div>';
    try {
      const data = await api("/events/" + encodeURIComponent(eventId));
      renderEventDetail(data);
    } catch (error) {
      $("#event-detail-content").innerHTML =
        '<div class="event-detail-topbar"><button type="button" class="event-back-button" data-back-events aria-label="Назад до подій">←</button><div class="event-detail-heading"><small>CHRONOS / ПОДІЇ</small><h1>Подію не завантажено</h1></div></div>' +
        '<div class="empty-state"><span class="empty-symbol">⌁</span><b>Не вдалося отримати дані</b><small>' + escapeHtml(error.message) + '</small></div>';
    }
  }

  async function registerForEvent(eventId) {
    const button = $("#event-action-button");
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

  async function cancelEventRegistration(eventId) {
    const button = $("#event-action-button");
    if (button) { button.disabled = true; button.textContent = "СКАСОВУЄМО..."; }
    try {
      await api("/events/" + encodeURIComponent(eventId) + "/cancel", {
        method: "POST",
        body: {}
      });
      toast("Реєстрацію скасовано");
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
    const backEvents = event.target.closest("[data-back-events]");
    if (backEvents) {
      showScreen("events");
      return;
    }
    const detailAction = event.target.closest("[data-event-action]");
    if (detailAction) {
      if (detailAction.dataset.eventAction === "register") return registerForEvent(state.currentEventId);
      if (detailAction.dataset.eventAction === "cancel") return cancelEventRegistration(state.currentEventId);
    }
    const navTarget = event.target instanceof Element ? event.target : event.target?.parentElement;
    const nav = navTarget?.closest("[data-nav]");
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


  const bottomNav = $(".bottom-nav");
  if (bottomNav) {
    let lastNavActivation = 0;
    let lastNavTarget = "";
    const activateBottomNav = (event) => {
      const target = event.target instanceof Element ? event.target : event.target?.parentElement;
      const item = target?.closest(".nav-item[data-nav]");
      if (!item || !item.dataset.nav) return;
      event.preventDefault();
      event.stopPropagation();
      const now = Date.now();
      const key = item.dataset.nav;
      if (key === lastNavTarget && now - lastNavActivation < 400) return;
      lastNavTarget = key;
      lastNavActivation = now;
      if (!showScreen(key)) return;
      closeModal();
      try {
        const loader = window.ChronosModules?.loadModule;
        if (typeof loader === "function") loader(key);
      } catch (error) {
        toast(error.message || "Не вдалося відкрити розділ.");
      }
    };
    bottomNav.addEventListener("pointerup", activateBottomNav);
    bottomNav.addEventListener("click", activateBottomNav);
  }

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
