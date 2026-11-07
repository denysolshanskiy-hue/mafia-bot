(() => {
  "use strict";
  const tg = window.Telegram && window.Telegram.WebApp;
  const initData = tg && tg.initData ? tg.initData : "";
  const S = {
    identity: null,
    achievements: [],
    collection: [],
    store: null,
    games: null,
    game: null,
    gameTimer: null,
    gameHideTimer: null,
    predictions: null,
    operations: null,
    rankings: null,
    notifications: null,
    adminTab: "schedule",
    adminImports: [],
    currentImport: null,
    importObjectUrl: null,
    storeFilter: "CR",
    rewardTab: "achievements",
    playerQuery: "",
    season: null
  };

  const $ = (selector, root) => (root || document).querySelector(selector);
  const $$ = (selector, root) => Array.from((root || document).querySelectorAll(selector));
  const esc = (value) => String(value === undefined || value === null ? "" : value).replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
  const money = (value) => Number(value || 0).toLocaleString("uk-UA");
  const labels = {
    finals: "ФІНАЛИ", season: "СЕЗОН", rewards: "НАГОРОДИ",
    predictions: "ПРОГНОЗИ", events: "ПОДІЇ", system: "СИСТЕМА"
  };

  function toast(message) {
    const node = $("#toast");
    if (!node) return;
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove("show"), 2800);
  }

  function headers(isJson) {
    const h = {};
    if (initData) h.Authorization = "tma " + initData;
    if (isJson) h["Content-Type"] = "application/json";
    return h;
  }

  async function api(path, options) {
    options = options || {};
    if (!initData) throw new Error("Відкрий Mini App через Telegram.");
    const body = options.body;
    const isForm = (typeof FormData !== "undefined") && (body instanceof FormData);
    const h = headers(body !== undefined && body !== null && !isForm);
    const response = await fetch("/api/chronos" + path, {
      method: options.method || "GET",
      headers: h,
      body: isForm ? body : (body === undefined || body === null ? undefined : JSON.stringify(body)),
      cache: "no-store"
    });
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(data.message || data.error || ("HTTP " + response.status));
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  async function apiImage(path) {
    const response = await fetch("/api/chronos" + path, { headers: headers(false), cache: "no-store" });
    if (!response.ok) throw new Error("Не вдалося завантажити файл імпорту.");
    return await response.blob();
  }

  function fmtDate(value) {
    if (!value) return "ДАТУ НЕ ВИЗНАЧЕНО";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return String(value);
    return d.toLocaleDateString("uk-UA", { day: "2-digit", month: "short", year: "numeric" }).replace(/\./g, "").toUpperCase();
  }

  function fmtTime(value) {
    if (!value) return "";
    return String(value).slice(0, 5);
  }

  function setSync(season) {
    if (!season) return;
    const percentValue = Number(season.sync_percent ?? 0);
    const percent = Number.isFinite(percentValue) ? Math.max(0, Math.min(100, percentValue)) : 0;
    const formatted = percent.toFixed(1) + "%";
    const statusText = season.status === "active" ? "СЕЗОН АКТИВНИЙ" : season.status === "paused" ? "СЕЗОН НА ПАУЗІ" : "ПОПЕРЕДНІЙ ПЕРЕГЛЯД";
    const towerBar = $("#sync-meter");
    const towerLabel = $("#sync-percent");
    const towerStatus = $("#sync-status-label");
    const towerTrack = $("#screen-tower .sync-track");
    const homeBar = $("#home-sync-meter");
    const homeLabel = $("#home-sync-percent");
    const homeStatus = $("#home-sync-status");
    const homeTrack = $("#home-sync-track");
    if (towerBar) towerBar.style.width = percent + "%";
    if (towerTrack) towerTrack.setAttribute("aria-valuenow", String(percent));
    if (towerLabel) towerLabel.textContent = formatted;
    if (towerStatus) towerStatus.textContent = statusText;
    if (homeBar) homeBar.style.width = percent + "%";
    if (homeLabel) homeLabel.textContent = formatted;
    if (homeStatus) homeStatus.textContent = statusText;
    if (homeTrack) homeTrack.setAttribute("aria-valuenow", String(percent));
    $$("#milestone-strip [data-milestone]").forEach((node) => {
      node.classList.toggle("reached", percent >= Number(node.dataset.milestone));
    });
  }

  function applyAvatarBase(code) {
    const allowed = new Set(["european_male","european_female","asian_male","asian_female","dark_male","dark_female","android_male","android_female"]);
    const base = allowed.has(code) ? code : "european_male";
    const profileAvatar = $(".avatar-person");
    if (profileAvatar) profileAvatar.className = "avatar-person " + base;
    const homeAvatar = $("#home-player-avatar");
    if (homeAvatar) homeAvatar.dataset.avatarBase = base;
  }

  async function loadIdentity() {
    try {
      S.identity = await api("/identity");
      const p = S.identity;
      const name = p.display_name || "Гість системи";
      if ($("#home-name")) $("#home-name").textContent = name;
      if ($("#profile-name")) $("#profile-name").textContent = name;
      if ($("#avatar-initial")) $("#avatar-initial").textContent = name.trim().slice(0, 1).toUpperCase() || "?";
      if ($("#home-profile-note")) $("#home-profile-note").textContent = p.profile_complete ? "ПРОФІЛЬ СИНХРОНІЗОВАНО" : "ЗАВЕРШИ /START У БОТІ";
      const balances = p.balances || {};
      const balanceKey = balances.CR != null ? "CR" : balances.EX != null ? "EX" : null;
      if ($("#home-balance")) $("#home-balance").textContent = balanceKey ? Number(balances[balanceKey] || 0).toLocaleString("uk-UA") + " " + balanceKey : "—";
      if ($("#profile-telegram")) $("#profile-telegram").textContent = p.profile_complete ? "KMC PLAYER REGISTRY" : "PROFILE NOT LINKED";
      if ($("#profile-role")) $("#profile-role").textContent = p.role === "admin" ? "ADMIN" : "INITIATE";
      if ($("#profile-title")) $("#profile-title").textContent = p.active_title ? String(p.active_title).toUpperCase() : "TELEGRAM · KMC";
      if ($("#admin-shortcut")) $("#admin-shortcut").hidden = p.role !== "admin";
      applyAvatarBase(p.avatar_base || "european_male");
      $$(".avatar-choice").forEach((el) => el.classList.toggle("selected", el.dataset.avatar === p.avatar_base));
      return p;
    } catch (error) {
      if (error.status !== 404) console.warn("Identity load:", error.message);
      S.identity = null;
      if ($("#admin-shortcut")) $("#admin-shortcut").hidden = true;
      return null;
    }
  }

  async function saveAvatar(code) {
    try {
      await api("/identity/avatar", { method: "POST", body: { avatar_base: code } });
      if (S.identity) S.identity.avatar_base = code;
      applyAvatarBase(code);
      $$(".avatar-choice").forEach((el) => el.classList.toggle("selected", el.dataset.avatar === code));
      toast("Основа аватара збережена.");
    } catch (error) { toast(error.message); }
  }

  async function loadAppearanceOptions() {
    const data = await api("/achievements");
    S.achievements = data.achievements || [];
    const earned = S.achievements.filter((a) => a.earned);
    const selects = [
      { id: "#identity-title", value: S.identity && S.identity.active_title, label: "Без звання" },
      { id: "#identity-badge-1", value: S.identity && S.identity.badges && S.identity.badges[0], label: "Без бейджа" },
      { id: "#identity-badge-2", value: S.identity && S.identity.badges && S.identity.badges[1], label: "Без бейджа" }
    ];
    selects.forEach((spec) => {
      const node = $(spec.id);
      if (!node) return;
      node.innerHTML = '<option value="">' + spec.label + '</option>' +
        earned.map((a) => '<option value="' + esc(a.achievement_code) + '">' + esc(a.name) + '</option>').join("");
      node.value = spec.value || "";
    });
  }

  async function saveAppearance() {
    const payload = {
      title: $("#identity-title") ? $("#identity-title").value || null : null,
      badges: [$("#identity-badge-1") ? $("#identity-badge-1").value : "", $("#identity-badge-2") ? $("#identity-badge-2").value : ""].filter(Boolean)
    };
    try {
      await api("/identity/appearance", { method: "POST", body: payload });
      await loadIdentity();
      toast("Ідентичність збережена.");
    } catch (error) { toast(error.message); }
  }

  async function loadMarket() {
    try {
      S.predictions = await api("/predictions");
      renderMarket();
    } catch (error) {
      if ($("#prediction-markets")) $("#prediction-markets").innerHTML = '<div class="empty-state"><span class="empty-symbol">◈</span><b>Біржу ще не запущено</b><small>' + esc(error.message) + '</small></div>';
    }
  }

  function renderMarket() {
    if (!S.predictions) return;
    const data = S.predictions;
    if ($("#ex-balance-market")) $("#ex-balance-market").textContent = money(data.balance_ex) + " EX";
    if ($("#prediction-rules-status")) $("#prediction-rules-status").textContent = "RULES: " + String(data.rules_status || "draft").toUpperCase();
    const target = $("#prediction-markets");
    if (!target) return;
    if (!data.markets.length) {
      target.innerHTML = '<div class="empty-state"><span class="empty-symbol">◈</span><b>Відкритих ринків поки немає</b><small>Організатор відкриє прогнози після імпорту підтвердженого рейтингу та затвердження економіки.</small></div>';
      return;
    }
    target.innerHTML = data.markets.map((m) => {
      const open = m.status === "open";
      const mine = m.my_bet;
      const candidates = m.candidates.map((p) =>
        '<option value="' + p.user_id + '">' + esc(p.display_name) +
        ' · ' + (Number(p.probability) * 100).toFixed(1) + '%' +
        ' · +' + Number(p.reward_ex) + ' EX</option>'
      ).join("");
      return '<article class="panel-card">' +
        '<div class="panel-top"><span class="panel-code">' + esc(m.market_type) + ' · EVENT #' + m.event_id + '</span><span class="status-chip ' + (open ? "" : "locked") + '">' + (open ? "OPEN" : "LOCKED") + '</span></div>' +
        '<h3>' + esc(m.event_title) + '</h3>' +
        '<p>' + esc(fmtDate(m.event_date)) + ' · ' + esc(fmtTime(m.event_time)) + ' · закриття: ' + esc(m.closes_at ? new Date(m.closes_at).toLocaleString("uk-UA") : "—") + '</p>' +
        (mine
          ? '<div class="notice-card"><span class="notice-mark">' + (mine.status === "won" ? "✓" : mine.status === "lost" ? "×" : "◈") + '</span><div><b>' +
            (mine.status === "won" ? "Прогноз справдився" : mine.status === "lost" ? "Прогноз не справдився" : mine.status === "refunded" ? "Прогноз анульовано" : "Твій прогноз прийнято") +
            '</b><p>' + esc((m.candidates.find(p => Number(p.user_id) === Number(mine.candidate_user_id)) || {}).display_name || "Обраний гравець") +
            ' · нагорода за влучання: ' + money(mine.reward_ex) + ' EX. За помилку EX не списуються.</p></div></div>'
          : (open
            ? '<div class="form-field"><label>ОБЕРИ ГРАВЦЯ · СЕБЕ ОБРАТИ НЕ МОЖНА</label><select data-bet-player="' + m.market_id + '">' + candidates + '</select></div>' +
              '<p class="muted-note">Безкоштовний прогноз. За правильну відповідь — 5–100 EX за ймовірністю; за неправильну — 0 втрат.</p>' +
              '<button class="secondary-button" data-place-bet="' + m.market_id + '">ЗРОБИТИ ПРОГНОЗ</button>'
            : '<p class="muted-note">Ринок закритий. Результат буде встановлений організатором після вечора.</p>')) +
        '</article>';
    }).join("");
  }

  async function placePrediction(marketId) {
    const player = $('[data-bet-player="' + marketId + '"]');
    if (!player) return;
    try {
      await api("/predictions/markets/" + marketId + "/bet", {
        method: "POST",
        body: { candidate_user_id: Number(player.value) }
      });
      toast("Безкоштовний прогноз прийнято.");
      await loadMarket();
    } catch (error) { toast(error.message); }
  }

  async function loadGames() {
    try {
      S.games = await api("/games");
      renderGames();
    } catch (error) {
      if ($("#games-list")) $("#games-list").innerHTML = '<div class="empty-state"><span class="empty-symbol">⌘</span><b>Симуляції недоступні</b><small>' + esc(error.message) + '</small></div>';
    }
  }

  function renderGames() {
    const target = $("#games-list");
    if (!target || !S.games) return;
    const screen = $("#screen-simulations");
    if (!S.games.season_active) {
      if (screen) screen.classList.add("simulation-inactive");
      target.innerHTML = '<img class="simulation-room-art" src="assets/chronos-v3/home/simulation-room.svg?v=01" alt="Симуляції CHRONOS — міні-ігри відкриються разом із сезоном">';
      return;
    }
    if (screen) screen.classList.remove("simulation-inactive");
    const adminNotice = S.games.admin_preview
      ? '<div class="notice-card"><span class="notice-mark">i</span><div><b>ADMIN TEST MODE</b><p>Доступ відкрито лише адміністратору до активації сезону. Тестові проходження не нараховують XP та не впливають на сезонний прогрес.</p></div></div>'
      : "";
    target.innerHTML = adminNotice + S.games.games.map((game) => {
      const attempts = Number(game.attempts_today || 0);
      return '<article class="game-card"><span class="game-symbol">' + (game.game_code === "MEMORY" ? "▦" : "⌘") + '</span>' +
        '<h3>' + esc(game.title) + '</h3><p>' + esc(game.description) + '</p>' +
        '<small>' + attempts + ' / 3 СЬОГОДНІ · ' + Number(game.completed || 0) + ' ЗАВЕРШЕНО</small>' +
        '<button class="secondary-button" data-start-game="' + game.game_code + '"' + (attempts >= 3 ? " disabled" : "") + '>ПОЧАТИ</button></article>';
    }).join("");
  }

  async function startGame(code) {
    try {
      const session = await api("/games/" + code, { method: "POST" });
      S.game = { id: session.session_id, code: code, state: session.state, feedback: [], attemptsLeft: 6 };
      renderGameSession();
      if (S.gameTimer) clearInterval(S.gameTimer);
      S.gameTimer = setInterval(() => {
        if (!S.game || !S.game.state) return;
        const node = $("#game-seconds");
        if (node) {
          S.game.state.seconds_left = Math.max(0, Number(S.game.state.seconds_left || 0) - 1);
          node.textContent = S.game.state.seconds_left + "s";
        }
      }, 1000);
    } catch (error) { toast(error.message); }
  }

  function renderGameSession() {
    const target = $("#active-game");
    if (!target || !S.game) return;
    target.hidden = false;
    const game = S.game;
    const seconds = game.state ? Number(game.state.seconds_left || 0) : 90;
    if (game.code === "CODE_BREAKER") {
      const guesses = (game.feedback || []).map((g, i) =>
        '<div class="guess-row"><span>' + (i + 1) + '. ' + esc(g.guess) + '</span><span>● ' + g.exact + ' &nbsp; ◇ ' + g.misplaced + '</span></div>'
      ).join("");
      target.innerHTML = '<div class="panel-top"><span class="panel-code">CODE BREAKER · SESSION</span><span class="game-timer" id="game-seconds">' + seconds + 's</span></div>' +
        '<h3>ЗЛАМАТИ КОД</h3><p class="modal-copy">4 різні цифри. ● — цифра та позиція правильні, ◇ — цифра є, позиція інша. 6 спроб.</p>' +
        '<form class="code-guess-form" id="code-guess-form"><input id="code-guess-input" type="text" inputmode="numeric" maxlength="4" pattern="[0-9]{4}" autocomplete="off" placeholder="••••" required><button class="primary-button" type="submit">ПЕРЕВІРИТИ</button></form>' +
        '<div class="guess-list">' + guesses + '</div><div class="row-actions"><button class="secondary-button" data-close-game>ЗАКРИТИ</button></div>';
      const input = $("#code-guess-input");
      if (input) input.focus();
    } else {
      const cells = game.state && game.state.cells ? game.state.cells : [];
      target.innerHTML = '<div class="panel-top"><span class="panel-code">MEMORY · SESSION</span><span class="game-timer" id="game-seconds">' + seconds + 's</span></div>' +
        '<h3>ЗНАЙТИ 6 ПАР</h3><p class="modal-copy">Знайди всі пари за 90 секунд. Ходи: ' + Number(game.state.moves || 0) + ' · Пари: ' + Number(game.state.pairs_found || 0) + ' / 6.</p>' +
        '<div class="memory-board">' + cells.map((cell) =>
          '<button class="memory-card ' + (cell.matched ? "matched" : cell.flipped ? "revealed" : "") + '" data-memory-card="' + cell.index + '"' +
          (cell.matched || cell.flipped || game.state.pending_hide ? " disabled" : "") + '>' + (cell.value ? esc(cell.value) : "⌁") + '</button>'
        ).join("") + '</div>' +
        (game.state.pending_hide ? '<p class="muted-note">Не збіглося — картки закриються автоматично.</p>' : "") +
        '<div class="row-actions"><button class="secondary-button" data-close-game>ЗАКРИТИ</button></div>';
      if (game.state.pending_hide && !S.gameHideTimer) {
        S.gameHideTimer = setTimeout(async () => {
          S.gameHideTimer = null;
          await gameAction("hide");
        }, 850);
      }
    }
  }

  async function gameAction(action, value) {
    if (!S.game) return;
    try {
      const result = await api("/games/sessions/" + S.game.id + "/action", {
        method: "POST", body: { action: action, value: value }
      });
      if (S.game.code === "CODE_BREAKER") {
        if (result.feedback) S.game.feedback.push(result.feedback);
        S.game.attemptsLeft = result.attempts_left;
        if (result.status !== "running") {
          if (S.gameTimer) clearInterval(S.gameTimer);
          S.game.state.seconds_left = 0;
          showGameResult(result.status, result.xp_awarded || 0);
          return;
        }
      } else {
        S.game.state = result.state;
        if (result.status !== "running") {
          if (S.gameTimer) clearInterval(S.gameTimer);
          showGameResult(result.status, result.xp_awarded || 0);
          return;
        }
      }
      renderGameSession();
    } catch (error) {
      if (error.data && error.data.status === "expired") {
        showGameResult("expired", 0);
      } else {
        toast(error.message);
      }
    }
  }

  function showGameResult(status, xp) {
    const target = $("#active-game");
    if (S.gameTimer) clearInterval(S.gameTimer);
    if (S.gameHideTimer) clearTimeout(S.gameHideTimer);
    S.gameTimer = null;
    S.gameHideTimer = null;
    if (!target) return;
    const good = status === "completed";
    target.innerHTML = '<div class="eyebrow">' + (good ? "SIMULATION COMPLETE" : "SIMULATION CLOSED") + '</div>' +
      '<h3>' + (good ? "ЗАВДАННЯ ВИКОНАНО" : "ЧАС ВИЧЕРПАНО") + '</h3>' +
      '<p class="modal-copy">' + (good ? "Нараховано " + xp + " XP. Повторні проходження не дають CR або EX." : "Ця спроба завершена. Можеш спробувати ще раз у межах денного ліміту.") + '</p>' +
      '<button class="secondary-button" data-close-game>ПОВЕРНУТИСЯ ДО СИМУЛЯЦІЙ</button>';
    loadGames();
    if (good && tg && tg.HapticFeedback) tg.HapticFeedback.notificationOccurred("success");
  }

  function closeGame() {
    S.game = null;
    if (S.gameTimer) clearInterval(S.gameTimer);
    if (S.gameHideTimer) clearTimeout(S.gameHideTimer);
    S.gameTimer = null;
    S.gameHideTimer = null;
    if ($("#active-game")) $("#active-game").hidden = true;
  }

  async function loadOperations() {
    try {
      S.operations = await api("/operations");
      renderOperations();
    } catch (error) {
      if ($("#operations-panel")) $("#operations-panel").innerHTML = '<div class="empty-state"><b>Операції недоступні</b><small>' + esc(error.message) + '</small></div>';
    }
  }

  function renderOperations() {
    const target = $("#operations-panel");
    if (!target || !S.operations) return;
    const d = S.operations;
    const p = d.participation || {};
    const a = d.attendance || {};
    const w = d.activity_score_weights || {};
    const qualified = p.qualified;
    target.innerHTML =
      '<div class="operation-grid">' +
        '<div class="operation-stat op-games"><small>ЗІГРАНО ІГОР</small><b>' + Number(p.games_played || 0) + '</b><span>із ' + Number(p.games_conducted || 0) + ' проведених</span></div>' +
        '<div class="operation-stat op-qualification"><small>КВАЛІФІКАЦІЯ</small><b style="color:' + (qualified ? "var(--cyan)" : "var(--gold)") + '">' + (qualified ? "YES" : "NO") + '</b><span>мінімум ' + Number(p.qualification_minimum || 0) + ' ігор</span></div>' +
        '<div class="operation-stat op-attendance"><small>ВІДВІДУВАННЯ</small><b>' + Number(a.percent || 0).toFixed(1) + '%</b><span>' + Number(a.attended || 0) + ' / ' + Number(a.eligible_evenings || 0) + ' вечорів</span></div>' +
        '<div class="operation-stat op-simulations"><small>SIMULATIONS</small><b>' + Number(d.mini_games_completed || 0) + '</b><span>верифікованих завершень</span></div>' +
      '</div>' +
      '<div class="panel-card operations-score-card"><div class="panel-top"><span class="panel-code">ACTIVITY SCORE · PREVIEW</span><span class="status-chip pending">' + esc(String(d.activity_score_status || "draft").toUpperCase()) + '</span></div>' +
        '<div class="operation-grid"><div class="operation-stat op-score-value"><small>ПОТОЧНИЙ БАЛ</small><b>' + Number((d.activity_score || {}).activity_score || 0).toFixed(2) + '</b><span>із 100</span></div><div class="operation-stat op-score-coefficient"><small>КОЕФІЦІЄНТ</small><b>' + Number(d.activity_coefficient || 0).toFixed(4) + '</b><span>бал / 100</span></div></div>' +
        '<p>Попередній розрахунок: відвідування ' + (w.attendance || 80) + '% · унікальна взаємодія з подією ' + (w.app || 15) + '% · мініігри ' + (w.minigame || 5) + '%. Це попередній бал, доки адміністратор не затвердить правило.</p></div>' +
      '<div class="section-heading compact"><div><div class="eyebrow">FINAL INVITATIONS</div><h2>Запрошення</h2></div></div>' +
      ((d.invitations || []).length ? d.invitations.map((i) =>
        '<div class="invitation-row"><strong>' + esc(i.slot_title) + ' · #' + i.rank_at_invite + '</strong><small>' + esc(i.status.toUpperCase()) + ' · DEADLINE ' + esc(new Date(i.deadline_at).toLocaleString("uk-UA")) + '</small>' +
        (i.status === "pending" ? '<div class="row-actions"><button class="secondary-button" data-invitation-response="' + i.invitation_id + '" data-response="accepted">ПІДТВЕРДИТИ</button><button class="danger-button" data-invitation-response="' + i.invitation_id + '" data-response="declined">ВІДМОВИТИСЯ</button></div>' : '') +
        '</div>'
      ).join("") : '<div class="empty-state"><b>Активних запрошень немає</b><small>Запрошення на фінал з’являться після формування TOP-10.</small></div>');
  }

  async function respondInvitation(id, response) {
    try {
      await api("/operations/invitations/" + id + "/respond", { method: "POST", body: { response: response } });
      toast(response === "accepted" ? "Участь підтверджена." : "Відмову збережено.");
      await loadOperations();
    } catch (error) { toast(error.message); }
  }

  async function loadRankings() {
    try {
      S.rankings = await api("/rankings");
      renderRankings();
    } catch (error) {
      if ($("#ranking-list")) $("#ranking-list").innerHTML = '<div class="empty-state"><b>Рейтинг недоступний</b><small>' + esc(error.message) + '</small></div>';
    }
  }

  function renderRankings() {
    const data = S.rankings;
    if (!data) return;
    const summary = $("#ranking-summary");
    const list = $("#ranking-list");
    const progressValue = Number(data.sync_percent ?? 0);
    const progressPercent = Number.isFinite(progressValue) ? Math.max(0, Math.min(100, progressValue)) : 0;
    summary.innerHTML = '<span>ПРОГРЕС СЕЗОНУ</span><strong>' + progressPercent.toFixed(1) + '%</strong>';
    if (!data.snapshot) {
      list.innerHTML = '<div class="empty-state"><span class="empty-symbol">↗</span><b>Ще немає підтвердженої статистики</b><small>Організатор має імпортувати рейтинг iMafia.</small></div>';
      return;
    }
    const q = data.qualification || {};
    const qHtml = '<div class="panel-card"><div class="panel-top"><span class="panel-code">FINAL QUALIFICATION</span><span class="status-chip ' + (q.qualified ? "" : "pending") + '">' + (q.qualified ? "QUALIFIED" : "NOT QUALIFIED") + '</span></div><p>Твої ігри: ' + Number(q.games_played || 0) + ' · проведено: ' + Number(q.games_conducted || 0) + ' · мінімум: ' + Number(q.minimum || 0) + '. Умова перераховується після кожного підтвердженого імпорту.</p></div>';
    list.innerHTML = qHtml + (data.players || []).map((p) =>
      '<div class="rank-row ' + (p.is_me ? "me" : "") + '"><span class="rank-no">' + String(p.rank_position).padStart(2, "0") + '</span><span class="rank-name">' + esc(p.display_name) + '<small class="rank-details">' + p.games_played + ' ІГОР · ' + Number(p.win_rate).toFixed(1) + '% WIN RATE</small></span><span class="rank-points">' + Number(p.points).toFixed(1) + '</span></div>'
    ).join("");
  }

  async function loadRewards(tab) {
    if (tab) S.rewardTab = tab;
    $$(".sub-tab[data-reward-tab]").forEach((el) => el.classList.toggle("active", el.dataset.rewardTab === S.rewardTab));
    if (S.rewardTab === "achievements") {
      const data = await api("/achievements");
      S.achievements = data.achievements || [];
      $("#reward-content").innerHTML = S.achievements.map((a) =>
        '<div class="achievement-card ' + (a.earned ? "earned" : "") + '"><span class="achievement-symbol">' + (a.earned ? "✦" : "◇") + '</span><span><b>' + esc(a.name) + '</b><small>' + esc(a.description) + '</small></span>' + (a.earned ? '<span class="earned-tag">EARNED</span>' : '') + '</div>'
      ).join("") || '<div class="empty-state"><b>Досягнень ще немає</b></div>';
    } else if (S.rewardTab === "collection") {
      const data = await api("/collection");
      S.collection = data.items || [];
      $("#reward-content").innerHTML = S.collection.map((item) =>
        '<div class="achievement-card earned"><span class="achievement-symbol">◇</span><span><b>' + esc(item.name) + '</b><small>' + esc(item.description) + ' · ' + esc(item.equip_slot.toUpperCase()) + '</small></span><span class="earned-tag">' + (item.equipped ? "EQUIPPED" : item.currency) + '</span></div>'
      ).join("") || '<div class="empty-state"><b>Колекція поки порожня</b><small>Нагороди та придбані предмети з’являться тут.</small></div>';
    } else {
      const data = await api("/ledger?limit=50");
      $("#reward-content").innerHTML = (data.entries || []).map((entry) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">' + esc(entry.reason_code.toUpperCase()) + '</span><span class="' + (Number(entry.amount) >= 0 ? "admin-success" : "admin-error") + '">' + (entry.amount > 0 ? "+" : "") + money(entry.amount) + ' ' + esc(entry.currency) + '</span></div><p>' + esc(fmtDate(entry.created_at)) + ' · ' + esc(entry.reference_key || "") + '</p></div>'
      ).join("") || '<div class="empty-state"><b>Історія поки порожня</b></div>';
    }
    if ($("#reward-balances") && S.identity) {
      const b = S.identity.balances || {};
      $("#reward-balances").innerHTML = '<span>CR / EX / XP</span><strong>' + money(b.CR) + ' / ' + money(b.EX) + ' / ' + money(b.XP) + '</strong>';
    }
  }

  async function loadStore(filter) {
    if (filter) S.storeFilter = filter;
    const data = await api("/store");
    S.store = data;
    const b = data.balances || {};
    $("#store-balances").textContent = money(b.CR) + " CR · " + money(b.EX) + " EX";
    $("#store-lock-note").hidden = !(S.storeFilter === "EX" && !data.ex_store_unlocked);
    $$(".sub-tab[data-store-filter]").forEach((el) => el.classList.toggle("active", el.dataset.storeFilter === S.storeFilter));
    const items = (data.items || []).filter((item) => item.currency === S.storeFilter);
    $("#store-items").innerHTML = items.map((item) => {
      const buyable = item.is_enabled && !item.owned && (item.currency !== "EX" || data.ex_store_unlocked);
      const action = item.owned
        ? (item.equipped ? "ЕКІПІРОВАНО" : "ЕКІПІРУВАТИ")
        : (item.is_enabled ? "ПРИДБАТИ" : "СКОРО");
      return '<article class="store-item"><div class="item-visual">' + esc(item.visual_key.slice(0, 3).toUpperCase()) + '</div><h3>' + esc(item.name) + '</h3><p>' + esc(item.description) + '</p><small>' + money(item.price) + ' ' + item.currency + ' · ' + esc(item.rarity.toUpperCase()) + '</small>' +
        '<button class="secondary-button" data-store-action="' + (item.owned ? "equip" : "buy") + '" data-item-id="' + item.item_id + '"' + ((!buyable && !item.owned) ? " disabled" : "") + '>' + action + '</button></article>';
    }).join("") || '<div class="empty-state"><b>У цьому магазині поки немає предметів</b><small>Каталог та ціни налаштовує адміністратор.</small></div>';
  }

  async function storeAction(itemId, action) {
    try {
      await api("/store/" + itemId + "/" + (action === "equip" ? "equip" : "buy"), { method: "POST" });
      toast(action === "equip" ? "Предмет екіпіровано." : "Предмет додано до колекції.");
      await loadIdentity();
      await loadStore();
      if (S.rewardTab === "collection") loadRewards("collection");
    } catch (error) { toast(error.message); }
  }

  async function loadNotifications() {
    try {
      const data = await api("/notifications");
      S.notifications = data;
      const prefsData = await api("/notifications/preferences");
      const prefs = prefsData.preferences || {};
      const prefNode = $("#notification-preferences");
      prefNode.innerHTML = Object.keys(labels).map((code) =>
        '<label class="preference-item"><span>' + labels[code] + '</span><input type="checkbox" data-notification-pref="' + code + '"' + (prefs[code] ? "" : " checked") + '></label>'
      ).join("");
      $("#unread-count").textContent = Number(data.unread_count || 0) + " UNREAD";
      const list = $("#notifications-list");
      list.innerHTML = (data.items || []).map((item) =>
        '<article class="notification-card ' + (!item.read_at ? "unread" : "") + '"><small>' + esc(labels[item.category] || item.category.toUpperCase()) + ' · ' + esc(fmtDate(item.created_at)) + '</small><b>' + esc(item.title) + '</b><p>' + esc(item.body) + '</p>' +
        (!item.read_at ? '<button class="secondary-button" data-mark-read="' + item.notification_id + '">ПОЗНАЧИТИ ПРОЧИТАНИМ</button>' : '') + '</article>'
      ).join("") || '<div class="empty-state"><span class="empty-symbol">◌</span><b>Нових сигналів немає</b><small>Важливі події з’являться тут.</small></div>';
    } catch (error) { toast(error.message); }
  }

  async function toggleNotificationPref(category, muted) {
    try {
      const data = await api("/notifications/preferences");
      const prefs = data.preferences || {};
      prefs[category] = muted;
      await api("/notifications/preferences", { method: "POST", body: { preferences: prefs } });
      await loadNotifications();
    } catch (error) { toast(error.message); }
  }

  async function markRead(id) {
    try {
      await api("/notifications/" + id + "/read", { method: "POST" });
      await loadNotifications();
    } catch (error) { toast(error.message); }
  }

  function adminMessage(node, text, ok) {
    if (node) node.innerHTML = '<div class="' + (ok ? "admin-success" : "admin-error") + '">' + esc(text) + '</div>';
  }

  async function loadAdminOverview() {
    const data = await api("/admin/overview");
    const s = data.season || {};
    const p = data.progress || {};
    $("#admin-overview").innerHTML =
      '<div class="admin-stat"><small>ПРОГРЕС СЕЗОНУ</small><b>' + Number(p.percent || 0).toFixed(1) + '%</b></div>' +
      '<div class="admin-stat"><small>ПІДТВЕРДЖЕНІ ІГРИ</small><b>' + Number(p.games || 0) + '</b></div>' +
      '<div class="admin-stat"><small>ГРАВЦІ</small><b>' + Number(p.players || 0) + '</b></div>' +
      '<div class="admin-stat"><small>ІМПОРТИ НА ПЕРЕВІРЦІ</small><b>' + Number(data.pending_imports || 0) + '</b></div>' +
      '<div class="admin-stat"><small>ВІДКРИТІ РИНКИ</small><b>' + Number(data.open_markets || 0) + '</b></div>';
    const settings = s.platform_settings || {};
    const pred = settings.predictions || {};
    const activity = settings.activity_score || {};
    const economy = settings.economy || {};
    $("#admin-content").innerHTML =
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">SEASON STATE</span><span class="status-chip pending">' + esc(String(s.status || "draft").toUpperCase()) + '</span></div>' +
        '<p>Статус сезону не вмикається автоматично. Економіка і правила мають бути затверджені до активації.</p>' +
        '<div class="admin-inline"><select id="admin-season-status" class="inline-input"><option value="draft">DRAFT</option><option value="active">ACTIVE</option><option value="paused">PAUSED</option><option value="completed">COMPLETED</option></select><button class="secondary-button" data-admin-action="season-status">ЗБЕРЕГТИ СТАТУС</button></div></div>' +
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">ACTIVITY SCORE · 100 POINTS</span><span class="status-chip pending">' + esc(String(activity.status || "draft").toUpperCase()) + '</span></div>' +
        '<p><b>80%</b> — відвідування; <b>15%</b> — верифіковані дії в Mini App (ліміт 13); <b>5%</b> — завершення мініігор (ліміт 5). Для фіналів у знаменник потрапляють тільки персональні запрошення. Відмова/no-show зменшує бал; не запрошений гравець не отримує штрафу.</p>' +
        '<div class="admin-inline"><select id="activity-status" class="inline-input"><option value="draft">DRAFT</option><option value="approved">APPROVED</option></select><button class="secondary-button" data-admin-action="save-activity-settings">ЗБЕРЕГТИ СТАТУС</button></div></div>' +
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">CLOSED ECONOMY · V1.0</span><span class="status-chip pending">' + esc(String(economy.status || "draft").toUpperCase()) + '</span></div>' +
        '<p><b>CR:</b> +5 за підтверджену гру, +10 за вечір. <b>XP:</b> +10 за гру, +5 за вечір; мінігра +20 за перше проходження кожного типу та +5 за повтор, до 10 повторів за сезон.</p>' +
        '<p>CR/EX можна витрачати тільки на косметику. XP не витрачається. Немає купівлі, передачі або виведення валюти. Призові 12 000 грн — окремі фіксовані виплати; активність їх не зменшує. Сезонний бонус 500 грн розподіляється окремо за коефіцієнтом.</p>' +
        '<div class="admin-inline"><select id="economy-status" class="inline-input"><option value="draft">DRAFT</option><option value="approved">APPROVED</option></select><button class="secondary-button" data-admin-action="save-economy-settings">ЗАТВЕРДИТИ ЕКОНОМІКУ</button></div></div>' +
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">PREDICTION EXCHANGE · NO STAKES</span><span class="status-chip pending">' + esc(String(pred.status || "draft").toUpperCase()) + '</span></div>' +
        '<p>Безкоштовно до 3 прогнозів на вечір. Себе обирати не можна. За правильний прогноз: очікувана винагорода 5 EX, розрахунок 5 / імовірність, межі 5–100 EX. За помилку — 0 втрат. Ліміт заробітку: 500 EX за сезон. EX Store відкривається після 6 прийнятих прогнозів.</p>' +
        '<div class="admin-inline"><select id="prediction-status" class="inline-input"><option value="draft">DRAFT</option><option value="approved">APPROVED</option></select><button class="secondary-button" data-admin-action="save-prediction-settings">ЗБЕРЕГТИ СТАТУС</button></div></div>' +
      '<div class="admin-row"><div class="panel-code">ECONOMIC CONTROL</div><p>Після затвердження правил використовуй «RECONCILE LEDGER» лише для повторного безпечного нарахування за вже імпортованими іграми. Ключі ідемпотентності не дадуть зарахувати CR/XP двічі.</p><button class="secondary-button" data-admin-action="reconcile-economy">RECONCILE LEDGER</button></div>';
    $("#admin-season-status").value = s.status || "draft";
    $("#activity-status").value = activity.status || "draft";
    $("#economy-status").value = economy.status || "draft";
    $("#prediction-status").value = pred.status || "draft";
  }

  async function loadAdminSchedule() {
    const data = await api("/admin/slots");
    const options = data.available_bot_events || [];
    $("#admin-content").innerHTML = (data.slots || []).map((slot) => {
      const optionsHtml = options.map((e) => '<option value="' + e.event_id + '">' + esc(e.title) + ' · #' + e.event_id + ' · ' + esc(fmtDate(e.event_date)) + '</option>').join("");
      const eventDate = slot.event_date || slot.planned_date || "";
      const eventTitle = slot.bot_event_id ? (slot.bot_event_title || slot.title || "") : (slot.title || "");
      return '<article class="admin-row"><div class="panel-top"><span class="panel-code">' + esc(slot.slot_code) + ' · #' + slot.sequence_no + '</span><span class="status-chip">' + esc(slot.slot_type) + '</span></div>' +
        '<h3>' + esc(slot.title) + '</h3><p>' + (slot.bot_event_id ? 'BOT EVENT: #' + slot.bot_event_id + ' · ' + esc(slot.bot_event_title || "") : "ЩЕ НЕ ПРИВʼЯЗАНО ДО ПОДІЇ БОТА") + '</p>' +
        '<div class="form-field"><label>ПЛАНОВА ДАТА</label><input type="date" class="inline-input" data-slot-date="' + slot.slot_id + '" value="' + (slot.planned_date || "") + '"></div>' +
        '<div class="form-field"><label>НАЗВА СЛОТУ</label><input class="inline-input" data-slot-title="' + slot.slot_id + '" value="' + esc(slot.title) + '"></div>' +
        '<div class="row-actions"><button class="secondary-button" data-save-slot="' + slot.slot_id + '">ЗБЕРЕГТИ СЛОТ</button>' +
        (!slot.bot_event_id ? '<div class="form-field"><label>СТВОРИТИ CHRONOS-ПОДІЮ У STAGING</label><input class="inline-input" data-event-title="' + slot.slot_id + '" value="' + esc(eventTitle) + '" placeholder="Назва події"><input type="date" class="inline-input" data-event-date="' + slot.slot_id + '" value="' + esc(eventDate) + '"><input type="time" class="inline-input" data-event-time="' + slot.slot_id + '" value="18:00"><button class="secondary-button" data-create-slot-event="' + slot.slot_id + '"' + (slot.status === "cancelled" ? ' disabled' : '') + '>СТВОРИТИ Й ПРИВʼЯЗАТИ</button></div>' +
          '<div class="form-field"><label>АБО ПРИВ’ЯЗАТИ НАЯВНУ CHRONOS-ПОДІЮ</label><select class="inline-input" data-slot-event="' + slot.slot_id + '"><option value="">ОБРАТИ CHRONOS-ПОДІЮ</option>' + optionsHtml + '</select><button class="secondary-button" data-link-slot="' + slot.slot_id + '">ПРИВʼЯЗАТИ</button></div>' :
          '<div class="form-field"><label>РЕДАГУВАТИ CHRONOS-ПОДІЮ У STAGING</label><input class="inline-input" data-event-title="' + slot.slot_id + '" value="' + esc(eventTitle) + '"><input type="date" class="inline-input" data-event-date="' + slot.slot_id + '" value="' + esc(eventDate) + '"><input type="time" class="inline-input" data-event-time="' + slot.slot_id + '" value="' + esc(slot.event_time || "18:00") + '"><select class="inline-input" data-event-status="' + slot.slot_id + '"><option value="active"' + (slot.bot_status === "active" ? ' selected' : '') + '>ACTIVE</option><option value="closed"' + (slot.bot_status === "closed" ? ' selected' : '') + '>CLOSED</option></select><button class="secondary-button" data-update-slot-event="' + slot.slot_id + '">ЗБЕРЕГТИ ПОДІЮ</button></div>') +
        (slot.slot_type !== "regular" ? '<button class="secondary-button" data-generate-invitations="' + slot.slot_id + '">СФОРМУВАТИ TOP-10 ЗАПРОШЕНЬ</button>' : '') +
        (slot.bot_status === "closed" ? '<button class="secondary-button" data-close-attendance="' + slot.slot_id + '">ЗАКРИТИ ВІДВІДУВАННЯ</button>' : '') +
        '</div></article>';
    }).join("") || '<div class="empty-state"><b>План сезону не знайдено</b></div>';
  }

  async function saveSlot(id) {
    const dateInput = $('[data-slot-date="' + id + '"]');
    const titleInput = $('[data-slot-title="' + id + '"]');
    try {
      await api("/admin/slots/" + id, { method: "POST", body: { planned_date: dateInput.value || null, title: titleInput.value } });
      toast("Слот збережено.");
      await loadAdminSchedule();
    } catch (error) { toast(error.message); }
  }

  async function linkSlot(id) {
    const select = $('[data-slot-event="' + id + '"]');
    if (!select || !select.value) return toast("Обери реальну CHRONOS-подію з бота.");
    try {
      await api("/admin/slots/" + id + "/link", { method: "POST", body: { event_id: Number(select.value) } });
      toast("Подію прив’язано.");
      await loadAdminSchedule();
    } catch (error) { toast(error.message); }
  }

  async function saveSlotEvent(id, create) {
    const title = $('[data-event-title="' + id + '"]');
    const eventDate = $('[data-event-date="' + id + '"]');
    const eventTime = $('[data-event-time="' + id + '"]');
    const body = { title: title.value, event_date: eventDate.value, event_time: eventTime.value };
    if (!create) body.status = $('[data-event-status="' + id + '"]').value;
    try {
      await api("/admin/slots/" + id + (create ? "/event" : "/event/update"), { method: "POST", body });
      toast(create ? "Подію створено й прив’язано у staging." : "Подію збережено у staging.");
      await loadAdminSchedule();
    } catch (error) { toast(error.message); }
  }

  async function loadAdminImports() {
    const data = await api("/admin/imports");
    S.adminImports = data.imports || [];
    $("#admin-content").innerHTML =
      '<div class="admin-row"><div class="panel-code">UPLOAD iMAFIA SCREENSHOT</div><p>Завантаж скриншот таблиці рейтингу або результатів вечора. OCR формує чернетку тексту; усі значення та ніки потрібно перевірити вручну перед підтвердженням.</p>' +
      '<form id="imafia-upload-form"><div class="form-field"><label>ТИП ІМПОРТУ</label><select id="import-kind" class="inline-input"><option value="ranking">RANKING SNAPSHOT</option><option value="game_results">GAME RESULTS</option></select></div>' +
      '<div class="form-field"><label>BOT EVENT ID (ДЛЯ РЕЗУЛЬТАТІВ)</label><input class="inline-input" id="import-event-id" type="number" placeholder="Наприклад: 125"></div>' +
      '<div class="form-field"><label>СКРИНШОТ (PNG / JPG / WEBP, ДО 8 МБ)</label><input class="inline-input" id="imafia-image" type="file" accept="image/png,image/jpeg,image/webp" required></div>' +
      '<button class="secondary-button" type="submit">ЗАВАНТАЖИТИ ТА РОЗПІЗНАТИ</button></form><div id="import-upload-result"></div></div>' +
      '<div class="admin-row" id="import-review-panel" hidden><div class="panel-code">MANUAL REVIEW / JSON</div><div id="import-image-preview"></div><pre id="import-ocr-text" class="ocr-text"></pre>' +
      '<p>Виправ усі поля. Для ranking потрібен масив players. Для game_results — масив games, кожна з рівно 10 гравцями з placement 1–10.</p>' +
      '<textarea id="import-review-json" class="form-field import-text" spellcheck="false"></textarea>' +
      '<div class="row-actions"><button class="secondary-button" data-admin-action="save-import-review">ЗБЕРЕГТИ ПЕРЕВІРКУ</button><button class="primary-button" data-admin-action="confirm-import">ПІДТВЕРДИТИ ІМПОРТ</button><button class="danger-button" data-admin-action="reject-import">ВІДХИЛИТИ</button></div><div id="import-confirm-result"></div></div>' +
      '<div class="section-heading compact"><div><div class="eyebrow">IMPORT HISTORY</div><h2>Завантаження</h2></div></div>' +
      S.adminImports.map((item) => '<div class="admin-row"><div class="panel-top"><span class="panel-code">#' + item.import_id + ' · ' + esc(item.import_type) + '</span><span class="status-chip ' + (item.status === "confirmed" ? "" : "pending") + '">' + esc(item.status.toUpperCase()) + '</span></div><p>' + esc(item.file_name) + ' · ' + esc(fmtDate(item.uploaded_at)) + ' · ' + esc(item.event_title || "") + '</p><button class="secondary-button" data-open-import="' + item.import_id + '">ВІДКРИТИ ІМПОРТ</button></div>').join("");
  }

  async function uploadImfiaScreenshot(form) {
    const input = $("#imafia-image");
    const file = input && input.files && input.files[0];
    if (!file) return toast("Оберіть зображення.");
    const data = new FormData();
    data.append("import_type", $("#import-kind").value);
    data.append("event_id", $("#import-event-id").value || "");
    data.append("image", file, file.name);
    try {
      const result = await api("/admin/imports/upload", { method: "POST", body: data });
      S.currentImport = result;
      $("#import-upload-result").innerHTML = '<div class="admin-success">Завантажено імпорт #' + result.import_id + '. OCR: ' + (result.ocr_error ? esc(result.ocr_error) : "готово") + '.</div>';
      await openImport(result.import_id);
      await loadAdminImports();
      // Restore the active review after the list refresh.
      await openImport(result.import_id);
    } catch (error) { adminMessage($("#import-upload-result"), error.message, false); }
  }

  function importTemplate(kind) {
    if (kind === "ranking") {
      return JSON.stringify({ players: [{ display_name: "Нік із iMafia", rank_position: 1, points: 0, games_played: 0, wins: 0, bonus_points: 0 }] }, null, 2);
    }
    return JSON.stringify({ games: [{ external_game_id: "imafia-game-id", game_number: 1, played_at: null, players: [
      { display_name: "Нік гравця 1", placement: 1, role_name: "Don", points: 0, bonus_points: 0, is_winner: true },
      { display_name: "Нік гравця 2", placement: 2, role_name: "Sheriff", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 3", placement: 3, role_name: "Peaceful", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 4", placement: 4, role_name: "Mafia", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 5", placement: 5, role_name: "Peaceful", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 6", placement: 6, role_name: "Mafia", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 7", placement: 7, role_name: "Peaceful", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 8", placement: 8, role_name: "Mafia", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 9", placement: 9, role_name: "Peaceful", points: 0, bonus_points: 0, is_winner: false },
      { display_name: "Нік гравця 10", placement: 10, role_name: "Peaceful", points: 0, bonus_points: 0, is_winner: false }
    ] }] }, null, 2);
  }

  async function openImport(id) {
    try {
      const detail = await api("/admin/imports/" + id);
      S.currentImport = detail;
      const panel = $("#import-review-panel");
      panel.hidden = false;
      $("#import-ocr-text").textContent = detail.ocr_text || "OCR не знайшов тексту. Заповни JSON вручну.";
      $("#import-review-json").value = detail.review_payload
        ? (typeof detail.review_payload === "string" ? JSON.stringify(JSON.parse(detail.review_payload), null, 2) : JSON.stringify(detail.review_payload, null, 2))
        : importTemplate(detail.import_type);
      if (S.importObjectUrl) URL.revokeObjectURL(S.importObjectUrl);
      try {
        const blob = await apiImage("/admin/imports/" + id + "/image");
        S.importObjectUrl = URL.createObjectURL(blob);
        $("#import-image-preview").innerHTML = '<img alt="Скриншот iMafia" class="import-preview" src="' + S.importObjectUrl + '">';
      } catch (_) { $("#import-image-preview").innerHTML = ""; }
    } catch (error) { toast(error.message); }
  }

  async function saveImportReview() {
    if (!S.currentImport) return;
    let payload;
    try { payload = JSON.parse($("#import-review-json").value); }
    catch (_) { return adminMessage($("#import-confirm-result"), "Помилка JSON. Перевір дужки та коми.", false); }
    try {
      const result = await api("/admin/imports/" + S.currentImport.import_id + "/review", { method: "POST", body: payload });
      adminMessage($("#import-confirm-result"), "Чернетку збережено. Рядків: " + result.rows, true);
      return true;
    } catch (error) { adminMessage($("#import-confirm-result"), error.message, false); return false; }
  }

  async function confirmImport() {
    if (!S.currentImport) return;
    try {
      const saved = await saveImportReview();
      if (!saved) return;
      const result = await api("/admin/imports/" + S.currentImport.import_id + "/confirm", { method: "POST", body: {} });
      adminMessage($("#import-confirm-result"), "Імпорт підтверджено: " + JSON.stringify(result), true);
      await loadAdminImports();
      await loadAdminOverview();
    } catch (error) { adminMessage($("#import-confirm-result"), error.message, false); }
  }

  async function rejectImport() {
    if (!S.currentImport) return;
    const reason = window.prompt("Причина відхилення імпорту:") || "";
    try {
      await api("/admin/imports/" + S.currentImport.import_id + "/reject", { method: "POST", body: { reason: reason } });
      S.currentImport = null;
      await loadAdminImports();
      toast("Імпорт відхилено.");
    } catch (error) { toast(error.message); }
  }

  async function loadAdminMarkets() {
    const data = await api("/admin/markets");
    const events = await api("/events");
    $("#admin-content").innerHTML =
      '<div class="admin-row"><div class="panel-code">OPEN PREDICTION MARKETS</div><p>Потрібен активний CHRONOS-захід, підтверджений рейтинг і затверджені правила економіки. Прогнози безкоштовні, ставки EX немає. Імовірність і винагорода фіксуються за поточним складом.</p>' +
      '<div class="form-field"><label>BOT EVENT ID</label><input id="market-event-id" class="inline-input" type="number" placeholder="ID CHRONOS-події"></div>' +
      '<div class="form-field"><label>ЧАС ЗАКРИТТЯ (ЛОКАЛЬНИЙ)</label><input id="market-close-at" class="inline-input" type="datetime-local"></div>' +
      '<button class="secondary-button" data-admin-action="open-markets">ВІДКРИТИ TOP1 / TOP2 / TOP3</button></div>' +
      '<div class="section-heading compact"><div><div class="eyebrow">MARKET CONTROL</div><h2>Поточні ринки</h2></div></div>' +
      (data.markets || []).map((market) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">#' + market.market_id + ' · ' + esc(market.market_type) + '</span><span class="status-chip">' + esc(market.status) + '</span></div>' +
        '<h3>' + esc(market.title) + '</h3><p>' + Number(market.bets) + ' ставок · ' + money(market.total_stake) + ' EX · ' + esc(market.closes_at ? new Date(market.closes_at).toLocaleString("uk-UA") : "—") + '</p>' +
        ((market.status === "open" || market.status === "locked") ? '<div class="admin-inline"><input class="inline-input" type="number" data-market-winner="' + market.market_id + '" placeholder="Telegram user_id переможця"><button class="secondary-button" data-settle-market="' + market.market_id + '">РОЗРАХУВАТИ</button><button class="danger-button" data-void-market="' + market.market_id + '">VOID / REFUND</button></div>' : '') +
        '</div>'
      ).join("") || '<div class="empty-state"><b>Ринків поки немає</b></div>';
  }

  async function openMarkets() {
    const eventId = Number($("#market-event-id").value);
    const raw = $("#market-close-at").value;
    if (!eventId || !raw) return toast("Вкажи event ID та час закриття.");
    try {
      await api("/predictions/markets/open", { method: "POST", body: { event_id: eventId, closes_at: new Date(raw).toISOString() } });
      toast("Три ринки відкрито.");
      await loadAdminMarkets();
    } catch (error) { toast(error.message); }
  }

  async function settleMarket(id, isVoid) {
    const winnerInput = $('[data-market-winner="' + id + '"]');
    const payload = isVoid ? { result: "void" } : { result: "settled", winning_user_id: Number(winnerInput && winnerInput.value) };
    if (!isVoid && !payload.winning_user_id) return toast("Вкажи Telegram user_id переможця.");
    try {
      await api("/predictions/markets/" + id + "/settle", { method: "POST", body: payload });
      toast(isVoid ? "Прогнози анульовано без втрати EX." : "Ринок розраховано.");
      await loadAdminMarkets();
    } catch (error) { toast(error.message); }
  }

  async function loadAdminPrizes() {
    const data = await api("/admin/prizes");
    $("#admin-content").innerHTML =
      '<div class="admin-row"><div class="panel-code">FIXED FINAL PRIZES</div><p>Суми призових не множаться на Activity Coefficient. Для створення виплати правило місця має бути ввімкнене; фактична виплата не виконується ботом.</p>' +
      '<div class="form-field"><label>SLOT ID</label><input id="prize-slot-id" class="inline-input" type="number"></div>' +
      '<div class="form-field"><label>EVENT TYPE</label><select id="prize-event-kind" class="inline-input"><option value="intermediate_final">INTERMEDIATE FINAL</option><option value="main_final">MAIN FINAL</option></select></div>' +
      '<textarea id="prize-awards-json" class="form-field import-text" spellcheck="false">' + esc(JSON.stringify({ awards: [{ user_id: 0, place: 1, base_amount_uah: 1000, activity_coefficient: 1.0 }] }, null, 2)) + '</textarea>' +
      '<button class="secondary-button" data-admin-action="draft-prizes">СТВОРИТИ ЧЕРНЕТКУ ФІКСОВАНОГО ПРИЗУ</button></div>' +
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">ACTIVITY BONUS · 500 UAH POOL</span><span class="status-chip pending">DRAFT UNTIL APPROVED</span></div>' +
      '<p>Пул розподіляється пропорційно Activity Score між початковим TOP-10 головного фіналу, який виконав 30% кваліфікацію. Відмова від запрошеного фіналу лишається пропущеним вечором і зменшує коефіцієнт. Не запрошені гравці до бонусного пулу не входять.</p>' +
      '<button class="secondary-button" data-admin-action="calculate-activity-bonus">РОЗРАХУВАТИ РОЗПОДІЛ 500 ГРН</button></div>' +
      '<div class="section-heading compact"><div><div class="eyebrow">ACTIVITY BONUS ALLOCATIONS</div><h2>Бонус активності</h2></div></div>' +
      (data.activity_bonus || []).map((a) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">#' + a.rank_at_lock + ' · ' + Number(a.activity_score).toFixed(2) + ' PTS</span><span class="status-chip ' + (a.status === "draft" ? "pending" : "") + '">' + esc(a.status.toUpperCase()) + '</span></div>' +
        '<h3>' + esc(a.display_name) + '</h3><p>Коефіцієнт ' + Number(a.activity_coefficient).toFixed(4) + ' · частка ' + money(a.allocation_amount_uah) + ' / ' + money(a.pool_amount_uah) + ' грн</p>' +
        (a.status === "draft" ? '<button class="secondary-button" data-bonus-status="' + a.allocation_id + '" data-status="approved">ЗАТВЕРДИТИ</button>' : a.status === "approved" ? '<button class="secondary-button" data-bonus-status="' + a.allocation_id + '" data-status="paid">ПОЗНАЧИТИ ОПЛАЧЕНИМ</button>' : '') +
        '</div>'
      ).join("") +
      '<div class="section-heading compact"><div><div class="eyebrow">PLACE AWARDS</div><h2>Фінальні призові</h2></div></div>' +
      (data.awards || []).map((a) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">' + esc(a.event_kind) + ' · #' + a.place + '</span><span class="status-chip ' + (a.status === "draft" ? "pending" : "") + '">' + esc(a.status) + '</span></div>' +
        '<h3>' + esc(a.display_name) + '</h3><p>Фіксована сума: ' + money(a.base_amount_uah) + ' грн · до виплати: ' + money(a.final_amount_uah) + ' грн</p>' +
        (a.status === "draft" ? '<button class="secondary-button" data-prize-status="' + a.award_id + '" data-status="approved">ЗАТВЕРДИТИ</button>' : a.status === "approved" ? '<button class="secondary-button" data-prize-status="' + a.award_id + '" data-status="paid">ПОЗНАЧИТИ ОПЛАЧЕНИМ</button>' : '') +
        '</div>'
      ).join("") +
      '<div class="section-heading compact"><div><div class="eyebrow">PRIZE RULES</div><h2>Правила фонду</h2></div></div>' +
      (data.rules || []).map((r) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">' + esc(r.event_kind) + ' · PLACE ' + r.place + '</span><span class="status-chip">' + (r.is_enabled ? "ACTIVE" : "DRAFT") + '</span></div><p>' + money(r.amount_uah) + ' грн · ' + esc(r.rule_note) + '</p>' +
        '<button class="secondary-button" data-prize-rule-toggle="' + esc(r.event_kind) + '" data-place="' + r.place + '" data-amount="' + r.amount_uah + '" data-enabled="' + (r.is_enabled ? "1" : "0") + '">' + (r.is_enabled ? "ВИМКНУТИ ПРАВИЛО" : "УВІМКНУТИ ПРАВИЛО") + '</button></div>'
      ).join("");
  }

  async function draftPrizes() {
    let awards;
    try { awards = JSON.parse($("#prize-awards-json").value).awards; }
    catch (_) { return toast("Некоректний JSON нагород."); }
    try {
      await api("/admin/prizes", { method: "POST", body: { slot_id: Number($("#prize-slot-id").value), event_kind: $("#prize-event-kind").value, awards: awards } });
      toast("Чернетку призів створено.");
      await loadAdminPrizes();
    } catch (error) { toast(error.message); }
  }

  async function togglePrizeRule(eventKind, place, amount, enabled) {
    const note = eventKind === "legacy"
      ? "Окремий бонусний пул Activity Score 500 грн; не зменшує фіксовані призові."
      : "Фіксована сума призу CHRONOS; не зменшується Activity Coefficient.";
    try {
      await api("/admin/prize-rules", {
        method: "POST",
        body: {
          event_kind: eventKind,
          place: Number(place),
          amount_uah: Number(amount),
          is_enabled: !enabled,
          rule_note: note
        }
      });
      toast(!enabled ? "Правило призів увімкнено." : "Правило призів вимкнено.");
      await loadAdminPrizes();
    } catch (error) { toast(error.message); }
  }

  async function prizeStatus(id, status) {
    try {
      await api("/admin/prizes/" + id + "/status", { method: "POST", body: { status: status } });
      toast("Статус нагороди змінено.");
      await loadAdminPrizes();
    } catch (error) { toast(error.message); }
  }

  function renderEconomyReport(report) {
    const currencies = report.currencies || {};
    const card = (code, title, color) => {
      const v = currencies[code] || {};
      const ratio = v.sink_to_faucet_ratio === null || v.sink_to_faucet_ratio === undefined
        ? "—"
        : (Number(v.sink_to_faucet_ratio) * 100).toFixed(1) + "%";
      return '<div class="admin-stat"><small>' + title + ' · ISSUE / SPEND</small>' +
        '<b>' + money(v.issued) + ' / ' + money(v.removed) + '</b>' +
        '<span>Net ' + money(v.net_change) + ' · holders ' + money(v.holders) + '</span>' +
        '<span>median ' + money(v.median_positive_balance) + ' · sink/faucet ' + ratio + '</span></div>';
    };
    const cash = report.cash_prizes || {};
    const planned = cash.planned || {};
    const catalog = report.catalog || {};
    const crCat = catalog.CR || {};
    const exCat = catalog.EX || {};
    const purchases = report.purchases || {};
    return '<div class="row-actions"><button class="secondary-button" data-admin-action="refresh-economy-report">ОНОВИТИ ЕКОНОМІЧНИЙ ЗВІТ</button></div>' +
      '<div class="section-heading compact"><div><div class="eyebrow">LIVE ECONOMY · LEDGER</div><h2>Фактичні потоки</h2></div></div>' +
      '<div class="admin-overview">' +
        card("CR", "CR", "cyan") + card("EX", "EX", "violet") + card("XP", "XP", "gold") +
      '</div>' +
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">COSMETIC SINKS</span><span class="status-chip">ONE-TIME ITEMS</span></div>' +
        '<p>CR: ' + Number(crCat.enabled_items || 0) + ' активних предметів · кошик ' + money(crCat.enabled_basket_price) + ' CR · покупки ' + money((purchases.CR || {}).total_spent) + ' CR.</p>' +
        '<p>EX: ' + Number(exCat.enabled_items || 0) + ' активних предметів · кошик ' + money(exCat.enabled_basket_price) + ' EX · покупки ' + money((purchases.EX || {}).total_spent) + ' EX.</p>' +
        '<p>Сумарна місткість каталогу за унікальними цінами: ' + money(report.scenario_model.cr_catalog_total_sink_capacity) + ' CR та ' + money(report.scenario_model.ex_catalog_total_sink_capacity) + ' EX. Це не прогноз витрат, а максимально доступний стік за поточним каталогом.</p></div>' +
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">UAH · FIXED COMMITMENT</span><span class="status-chip">NO CURRENCY CONVERSION</span></div>' +
        '<p>Проміжні фінали: ' + money(planned.intermediate_finals) + ' грн · Main Final: ' + money(planned.main_final) + ' грн · окремий бонус: ' + money(planned.activity_bonus) + ' грн.</p>' +
        '<h3>Усього бюджет сезону: ' + money(planned.total_commitment) + ' грн</h3>' +
        '<p>Фактичні призові: drafted ' + money(cash.fixed_awards_drafted) + ' · approved ' + money(cash.fixed_awards_approved) + ' · paid ' + money(cash.fixed_awards_paid) + ' грн.</p>' +
        '<p>Бонус: розраховано ' + Number(cash.activity_bonus_allocations || 0) + ' гравців · виділено ' + money(cash.activity_bonus_allocated) + ' / ' + money(cash.activity_bonus_pool) + ' грн · paid ' + money(cash.activity_bonus_paid) + ' грн.</p></div>' +
      '<div class="admin-row"><div class="panel-code">MODEL ASSUMPTIONS</div><p>CR/EX — косметичні валюти; XP — progression only. Немає купівлі, переказу чи cash-out. Баланси переносяться між сезонами, тому каталог потрібно поповнювати новими унікальними косметичними предметами, не створюючи pay-to-win переваг.</p></div>';
  }

  async function loadAdminEconomy() {
    const [data, report] = await Promise.all([
      api("/store"),
      api("/admin/economy/report")
    ]);
    const html = renderEconomyReport(report) +
      '<div class="section-heading compact"><div><div class="eyebrow">LEDGER CONTROL</div><h2>Корекції</h2></div></div>' +
      '<div class="admin-row"><div class="panel-code">MANUAL CORRECTION</div><p>Корекції CR/XP — лише з причиною та унікальним ключем. EX можна позитивно коригувати лише як явне виправлення; купівлі та передачі EX немає.</p>' +
      '<div class="form-field"><label>PLAYER USER ID</label><input id="adjust-user" class="inline-input" type="number"></div>' +
      '<div class="admin-inline"><select id="adjust-currency" class="inline-input"><option>CR</option><option>XP</option><option>EX</option></select><input id="adjust-amount" class="inline-input" type="number" placeholder="± amount"></div>' +
      '<div class="form-field"><label>ПРИЧИНА</label><input id="adjust-reason" class="inline-input" placeholder="Correction: ..."></div>' +
      '<div class="form-field"><label>IDEMPOTENCY KEY</label><input id="adjust-key" class="inline-input" placeholder="unique-reference"></div>' +
      '<button class="secondary-button" data-admin-action="ledger-adjust">ЗАПИСАТИ КОРЕКЦІЮ</button></div>' +
      '<div class="section-heading compact"><div><div class="eyebrow">CATALOG CONTROL</div><h2>Каталог предметів</h2></div></div>' +
      (data.items || []).map((item) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">' + esc(item.item_code) + ' · ' + esc(item.currency) + '</span><span class="status-chip ' + (item.is_enabled ? "" : "pending") + '">' + (item.is_enabled ? "ENABLED" : "DISABLED") + '</span></div><h3>' + esc(item.name) + '</h3>' +
        '<div class="admin-inline"><input class="inline-input" type="number" min="0" value="' + item.price + '" data-item-price="' + item.item_id + '"><label class="preference-item"><span>ENABLED</span><input type="checkbox" data-item-enabled="' + item.item_id + '"' + (item.is_enabled ? " checked" : "") + '></label><button class="secondary-button" data-save-item="' + item.item_id + '">ЗБЕРЕГТИ</button></div></div>'
      ).join("");
    $("#admin-content").innerHTML = html;
  }

  async function saveCatalogItem(id) {
    const price = Number($('[data-item-price="' + id + '"]').value);
    const enabled = $('[data-item-enabled="' + id + '"]').checked;
    try {
      await api("/admin/catalog/" + id, { method: "POST", body: { price: price, is_enabled: enabled } });
      toast("Каталог оновлено.");
      await loadAdminEconomy();
    } catch (error) { toast(error.message); }
  }

  async function adjustLedger() {
    const payload = {
      user_id: Number($("#adjust-user").value),
      currency: $("#adjust-currency").value,
      amount: Number($("#adjust-amount").value),
      reason: $("#adjust-reason").value.trim(),
      idempotency_key: $("#adjust-key").value.trim()
    };
    try {
      await api("/admin/economy/adjust", { method: "POST", body: payload });
      toast("Корекцію записано в журнал.");
      await loadAdminEconomy();
    } catch (error) { toast(error.message); }
  }

  async function loadAdminPlayers() {
    const q = $("#admin-player-query") ? $("#admin-player-query").value : "";
    const data = await api("/admin/players?q=" + encodeURIComponent(q));
    $("#admin-content").innerHTML =
      '<div class="form-field"><label>ПОШУК ГРАВЦЯ</label><input id="admin-player-query" class="inline-input" placeholder="Нік або username" value="' + esc(q) + '"></div><button class="secondary-button" data-admin-action="search-players">ШУКАТИ</button>' +
      (data.players || []).map((p) =>
        '<div class="admin-row"><div class="panel-top"><span class="panel-code">ID ' + p.user_id + '</span><span class="status-chip">' + esc(p.role) + '</span></div><h3>' + esc(p.display_name || p.username || "Без ніку") + '</h3><p>CR ' + money(p.cr) + ' · EX ' + money(p.ex) + ' · XP ' + money(p.xp) + ' · ' + (p.is_active ? "ACTIVE" : "DISABLED") + '</p></div>'
      ).join("");
  }

  async function loadAdminAudit() {
    const data = await api("/admin/audit");
    $("#admin-content").innerHTML = (data.entries || []).map((a) =>
      '<div class="admin-row"><div class="panel-top"><span class="panel-code">' + esc(a.action_code.toUpperCase()) + '</span><span class="section-code">' + esc(fmtDate(a.created_at)) + '</span></div><h3>' + esc(a.actor_name || "SYSTEM") + ' · ' + esc(a.target_type) + ' ' + esc(a.target_id || "") + '</h3><p>' + esc(JSON.stringify(a.details)) + '</p></div>'
    ).join("") || '<div class="empty-state"><b>Audit Log порожній</b></div>';
  }

  async function saveAdminSettings(kind) {
    try {
      let payload;
      if (kind === "season-status") {
        payload = { status: $("#admin-season-status").value };
        await api("/admin/season/status", { method: "POST", body: payload });
      } else if (kind === "save-activity-settings") {
        payload = { activity_score: { status: $("#activity-status").value, weights: {
          attendance: 80, app: 15, minigame: 5
        } } };
        await api("/admin/settings", { method: "POST", body: payload });
      } else if (kind === "save-economy-settings") {
        payload = { economy: { status: $("#economy-status").value } };
        await api("/admin/settings", { method: "POST", body: payload });
      } else if (kind === "save-prediction-settings") {
        payload = { predictions: { status: $("#prediction-status").value } };
        await api("/admin/settings", { method: "POST", body: payload });
      } else if (kind === "reconcile-economy") {
        const result = await api("/admin/economy/reconcile", { method: "POST", body: {} });
        toast("Нарахування звірено: +" + money(result.currency_minted.CR) + " CR, +" + money(result.currency_minted.XP) + " XP.");
        await loadAdminOverview();
        return;
      }
      toast("Налаштування збережено.");
      await loadAdminOverview();
    } catch (error) { toast(error.message); }
  }

  async function calculateActivityBonus() {
    try {
      const result = await api("/admin/season-bonus/calculate", { method: "POST", body: {} });
      toast("Розраховано " + result.eligible_players + " учасників; розподілено " + money(result.distributed_uah) + " грн.");
      await loadAdminPrizes();
    } catch (error) { toast(error.message); }
  }

  async function updateActivityBonusStatus(id, status) {
    try {
      await api("/admin/season-bonus/" + id + "/status", { method: "POST", body: { status: status } });
      toast("Статус бонусу змінено.");
      await loadAdminPrizes();
    } catch (error) { toast(error.message); }
  }

  async function loadAdminTab(tab) {
    S.adminTab = tab || S.adminTab;
    $$(".admin-tab").forEach((el) => el.classList.toggle("active", el.dataset.adminTab === S.adminTab));
    try {
      if (S.adminTab === "schedule") return await loadAdminSchedule();
      if (S.adminTab === "imports") return await loadAdminImports();
      if (S.adminTab === "markets") return await loadAdminMarkets();
      if (S.adminTab === "prizes") return await loadAdminPrizes();
      if (S.adminTab === "economy") return await loadAdminEconomy();
      if (S.adminTab === "players") return await loadAdminPlayers();
      if (S.adminTab === "audit") return await loadAdminAudit();
    } catch (error) {
      $("#admin-content").innerHTML = '<div class="empty-state"><b>Помилка завантаження</b><small>' + esc(error.message) + '</small></div>';
    }
  }

  async function loadAdmin() {
    if (!S.identity || S.identity.role !== "admin") {
      toast("Адміністративний доступ відсутній.");
      return;
    }
    try {
      await loadAdminOverview();
      await loadAdminTab("schedule");
    } catch (error) { toast(error.message); }
  }

  async function loadModule(name) {
    try {
      if (name === "market") return await loadMarket();
      if (name === "simulations") return await loadGames();
      if (name === "operations") return await loadOperations();
      if (name === "rankings") return await loadRankings();
      if (name === "rewards") return await loadRewards();
      if (name === "store") return await loadStore();
      if (name === "notifications") return await loadNotifications();
      if (name === "admin") return await loadAdmin();
      if (name === "profile") {
        await loadIdentity();
        await loadAppearanceOptions();
      }
      if (name === "home") await loadIdentity();
      if (name === "tower" || name === "home") {
        const data = await api("/events");
        S.season = data.season;
        setSync(data.season);
      }
    } catch (error) {
      toast(error.message);
    }
  }

  document.addEventListener("click", async (event) => {
    const nav = event.target.closest("[data-nav]");
    if (nav && nav.dataset.nav) {
      const name = nav.dataset.nav;
      setTimeout(() => loadModule(name), 40);
      return;
    }

    const avatar = event.target.closest("[data-avatar]");
    if (avatar) return saveAvatar(avatar.dataset.avatar);

    const placeBet = event.target.closest("[data-place-bet]");
    if (placeBet) return placePrediction(placeBet.dataset.placeBet);

    const start = event.target.closest("[data-start-game]");
    if (start) return startGame(start.dataset.startGame);

    const mem = event.target.closest("[data-memory-card]");
    if (mem && S.game && S.game.code === "MEMORY") return gameAction("flip", Number(mem.dataset.memoryCard));

    const close = event.target.closest("[data-close-game]");
    if (close) { closeGame(); return; }

    const inv = event.target.closest("[data-invitation-response]");
    if (inv) return respondInvitation(inv.dataset.invitationResponse, inv.dataset.response);

    const rewardTab = event.target.closest("[data-reward-tab]");
    if (rewardTab) return loadRewards(rewardTab.dataset.rewardTab);

    const storeTab = event.target.closest("[data-store-filter]");
    if (storeTab) return loadStore(storeTab.dataset.storeFilter);

    const storeActionButton = event.target.closest("[data-store-action]");
    if (storeActionButton) return storeAction(storeActionButton.dataset.itemId, storeActionButton.dataset.storeAction);

    const mark = event.target.closest("[data-mark-read]");
    if (mark) return markRead(mark.dataset.markRead);

    const adminTab = event.target.closest("[data-admin-tab]");
    if (adminTab) return loadAdminTab(adminTab.dataset.adminTab);

    const saveSlotButton = event.target.closest("[data-save-slot]");
    if (saveSlotButton) return saveSlot(saveSlotButton.dataset.saveSlot);

    const link = event.target.closest("[data-link-slot]");
    if (link) return linkSlot(link.dataset.linkSlot);

    const createEvent = event.target.closest("[data-create-slot-event]");
    if (createEvent) return saveSlotEvent(createEvent.dataset.createSlotEvent, true);

    const updateEvent = event.target.closest("[data-update-slot-event]");
    if (updateEvent) return saveSlotEvent(updateEvent.dataset.updateSlotEvent, false);

    const generate = event.target.closest("[data-generate-invitations]");
    if (generate) {
      try { await api("/admin/slots/" + generate.dataset.generateInvitations + "/invitations", { method: "POST", body: {} }); toast("Запрошення сформовано."); await loadAdminSchedule(); }
      catch (error) { toast(error.message); }
      return;
    }

    const closeAttendance = event.target.closest("[data-close-attendance]");
    if (closeAttendance) {
      try { await api("/admin/slots/" + closeAttendance.dataset.closeAttendance + "/close-attendance", { method: "POST", body: {} }); toast("Відвідування закрито."); await loadAdminSchedule(); }
      catch (error) { toast(error.message); }
      return;
    }

    const openImportButton = event.target.closest("[data-open-import]");
    if (openImportButton) return openImport(openImportButton.dataset.openImport);

    const settle = event.target.closest("[data-settle-market]");
    if (settle) return settleMarket(settle.dataset.settleMarket, false);
    const voidMarket = event.target.closest("[data-void-market]");
    if (voidMarket) return settleMarket(voidMarket.dataset.voidMarket, true);

    const draft = event.target.closest("[data-admin-action]");
    if (draft) {
      const action = draft.dataset.adminAction;
      if (action === "open-markets") return openMarkets();
      if (action === "draft-prizes") return draftPrizes();
      if (action === "ledger-adjust") return adjustLedger();
      if (action === "save-activity-settings" || action === "save-economy-settings" || action === "save-prediction-settings" || action === "season-status" || action === "reconcile-economy") return saveAdminSettings(action);
      if (action === "calculate-activity-bonus") return calculateActivityBonus();
      if (action === "refresh-economy-report") return loadAdminEconomy();
      if (action === "search-players") return loadAdminPlayers();
      if (action === "save-import-review") return saveImportReview();
      if (action === "confirm-import") return confirmImport();
      if (action === "reject-import") return rejectImport();
    }

    const saveItem = event.target.closest("[data-save-item]");
    if (saveItem) return saveCatalogItem(saveItem.dataset.saveItem);

    const prize = event.target.closest("[data-prize-status]");
    if (prize) return prizeStatus(prize.dataset.prizeStatus, prize.dataset.status);
    const prizeRule = event.target.closest("[data-prize-rule-toggle]");
    if (prizeRule) return togglePrizeRule(
      prizeRule.dataset.prizeRuleToggle,
      prizeRule.dataset.place,
      prizeRule.dataset.amount,
      prizeRule.dataset.enabled === "1"
    );
    const bonus = event.target.closest("[data-bonus-status]");
    if (bonus) return updateActivityBonusStatus(bonus.dataset.bonusStatus, bonus.dataset.status);

    const appearance = event.target.closest("#save-appearance");
    if (appearance) return saveAppearance();
  });

  document.addEventListener("submit", async (event) => {
    if (event.target && event.target.id === "code-guess-form") {
      event.preventDefault();
      const input = $("#code-guess-input");
      const guess = input ? input.value.trim() : "";
      if (!/^[0-9]{4}$/.test(guess) || new Set(guess).size !== 4) return toast("Введи чотири різні цифри.");
      if (input) input.value = "";
      await gameAction("guess", guess);
      return;
    }
    if (event.target && event.target.id === "imafia-upload-form") {
      event.preventDefault();
      await uploadImfiaScreenshot(event.target);
    }
  });

  document.addEventListener("change", (event) => {
    const pref = event.target.closest("[data-notification-pref]");
    if (pref) toggleNotificationPref(pref.dataset.notificationPref, !pref.checked);
  });

  // Keep the extended screens ready while retaining the original app's base navigation and event modal.
  if (initData) {
    loadIdentity().then(async () => {
      const calendar = await api("/events").catch(() => null);
      if (calendar) {
        S.season = calendar.season;
        setSync(calendar.season);
      }
    }).catch(() => {});
  }

  window.ChronosModules = { loadModule: loadModule, refreshIdentity: loadIdentity };
})();
