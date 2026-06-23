(function () {
  // /reader/read-along/{book_id}
  var parts = location.pathname.split("/").filter(Boolean);
  var bookId = parts[parts.length - 1];

  var bgImage = document.getElementById("bg-image");
  var titleEl = document.getElementById("title");
  var pageNum = document.getElementById("page-num");
  var pageTotal = document.getElementById("page-total");
  var starsEl = document.getElementById("stars");
  var wordsEl = document.getElementById("words");
  var promptEl = document.getElementById("prompt");
  var bannerEl = document.getElementById("banner");

  var readerScreen = document.getElementById("reader-screen");
  var rewardScreen = document.getElementById("reward-screen");
  var closedScreen = document.getElementById("closed-screen");
  var errorScreen = document.getElementById("error-screen");

  var currentPage = 0;
  var wordSpans = [];
  var imageRetryTimer = null;

  function showScreen(screen) {
    [readerScreen, rewardScreen, closedScreen, errorScreen].forEach(function (s) {
      s.classList.remove("active");
    });
    screen.classList.add("active");
  }

  function renderStars(n) {
    var s = "";
    for (var i = 0; i < n; i++) s += "⭐";
    starsEl.textContent = s;
  }

  function tapWord(index) {
    fetch("/reader/read-along/tap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index: index }),
    }).catch(function () {});
  }

  function renderWords(words, states) {
    wordsEl.innerHTML = "";
    wordSpans = [];
    (words || []).forEach(function (w, i) {
      var span = document.createElement("span");
      span.className = "word";
      span.textContent = w;
      span.setAttribute("data-index", i);
      if (states && states[i]) span.classList.add(states[i]);
      span.addEventListener("click", function () {
        tapWord(i);
      });
      wordsEl.appendChild(span);
      wordSpans.push(span);
    });
  }

  var STATES = ["bounce", "highlight", "sound_out", "success"];

  function applyCue(index, state) {
    var span = wordSpans[index];
    if (!span) return;
    STATES.forEach(function (s) {
      span.classList.remove(s);
    });
    if (state && state !== "clear") {
      // restart animation if re-applying the same class
      void span.offsetWidth;
      span.classList.add(state);
    }
  }

  function loadImage(page, attempt) {
    attempt = attempt || 0;
    if (imageRetryTimer) {
      clearTimeout(imageRetryTimer);
      imageRetryTimer = null;
    }
    var url = "/reader/api/books/" + bookId + "/pages/" + page + "/image";
    var probe = new Image();
    probe.onload = function () {
      bgImage.src = url;
    };
    probe.onerror = function () {
      // Illustrations are generated in the background; retry a few times.
      if (attempt < 8) {
        imageRetryTimer = setTimeout(function () {
          loadImage(page, attempt + 1);
        }, 2500);
      } else {
        bgImage.removeAttribute("src");
      }
    };
    probe.src = url + "?t=" + attempt;
  }

  function onPage(data) {
    showScreen(readerScreen);
    currentPage = data.page;
    titleEl.textContent = data.title || "";
    pageNum.textContent = (data.page + 1).toString();
    pageTotal.textContent = (data.total || 1).toString();
    renderStars(data.stars || 0);
    renderWords(data.words, data.word_states);
    promptEl.textContent = data.sel_prompt || "";
    bannerEl.style.display = "block";
    loadImage(data.page, 0);
  }

  function onFinish(data) {
    var rewardStars = document.getElementById("reward-stars");
    var rewardText = document.getElementById("reward-text");
    var s = "";
    for (var i = 0; i < (data.stars || 0); i++) s += "⭐";
    rewardStars.textContent = s;
    rewardText.textContent = data.wrapup || "";
    showScreen(rewardScreen);
  }

  function handleEvent(data) {
    switch (data.event) {
      case "read_along_page":
        onPage(data);
        break;
      case "word_cue":
        applyCue(data.index, data.state);
        break;
      case "stars":
        renderStars(data.stars || 0);
        break;
      case "read_along_finish":
        onFinish(data);
        break;
      case "read_along_closed":
        showScreen(closedScreen);
        break;
      case "heartbeat":
      default:
        break;
    }
  }

  // SSE connection with reconnect
  var evtSource = null;
  var reconnectAttempts = 0;
  var MAX_RECONNECT = 10;

  function connectSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource("/reader/read-along/events");

    evtSource.onopen = function () {
      reconnectAttempts = 0;
    };

    evtSource.onmessage = function (event) {
      try {
        handleEvent(JSON.parse(event.data));
      } catch (e) {
        console.error("SSE parse error:", e);
      }
    };

    evtSource.onerror = function () {
      evtSource.close();
      evtSource = null;
      if (reconnectAttempts >= MAX_RECONNECT) return;
      var delay = Math.min(3000 * Math.pow(2, reconnectAttempts), 30000);
      reconnectAttempts++;
      setTimeout(connectSSE, delay);
    };
  }

  window.addEventListener("beforeunload", function () {
    if (evtSource) evtSource.close();
  });

  // Initial state (in case the session already started before this page loaded)
  fetch("/reader/read-along/state")
    .then(function (r) {
      if (!r.ok) throw new Error("no session");
      return r.json();
    })
    .then(function (snap) {
      if (snap.status === "finished") {
        onFinish(snap);
      } else {
        onPage(snap);
      }
    })
    .catch(function () {
      showScreen(errorScreen);
    })
    .finally(function () {
      connectSSE();
    });
})();
