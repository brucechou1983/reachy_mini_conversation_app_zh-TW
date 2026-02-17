(function () {
  const loadingScreen = document.getElementById("loading-screen");
  const readerScreen = document.getElementById("reader-screen");
  const endScreen = document.getElementById("end-screen");
  const pageImage = document.getElementById("page-image");
  const pageText = document.getElementById("page-text");
  const pageNum = document.getElementById("page-num");
  const pageTotal = document.getElementById("page-total");
  const loadingTitle = document.getElementById("loading-title");

  function showScreen(screen) {
    document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
    screen.classList.add("active");
  }

  let evtSource = null;

  function connectSSE() {
    if (evtSource) {
      evtSource.close();
    }
    evtSource = new EventSource("/reader/events");

    evtSource.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleEvent(data);
      } catch (e) {
        console.error("SSE parse error:", e);
      }
    };

    evtSource.onerror = () => {
      evtSource.close();
      evtSource = null;
      // Reconnect after 3 seconds
      setTimeout(connectSSE, 3000);
    };
  }

  function handleEvent(data) {
    switch (data.event) {
      case "generating":
        showScreen(loadingScreen);
        if (data.title) {
          loadingTitle.textContent = data.title;
        }
        break;

      case "story_ready":
        showScreen(loadingScreen);
        loadingScreen.querySelector("h1").textContent = "故事準備好了！";
        if (data.title) {
          loadingTitle.textContent = data.title;
        }
        break;

      case "page_change":
        showPage(data);
        break;

      case "story_closed":
        showScreen(endScreen);
        break;

      case "heartbeat":
        break;
    }
  }

  function showPage(data) {
    showScreen(readerScreen);
    pageText.textContent = data.text || "";
    pageNum.textContent = (data.page + 1).toString();
    pageTotal.textContent = (data.total || 8).toString();

    if (data.image_b64) {
      var mime = data.image_mime || "image/png";
      pageImage.src = "data:" + mime + ";base64," + data.image_b64;
      pageImage.style.display = "block";
    } else {
      pageImage.src = "";
      pageImage.style.display = "none";
    }

    // Trigger page-turn animation
    const container = document.querySelector(".page-container");
    container.style.animation = "none";
    container.offsetHeight; // trigger reflow
    container.style.animation = "fadeIn 0.5s ease";
  }

  // Initial load - check for existing story state
  async function init() {
    try {
      const resp = await fetch("/reader/story");
      if (resp.ok) {
        const story = await resp.json();
        if (story.status === "generating") {
          showScreen(loadingScreen);
          if (story.title) loadingTitle.textContent = story.title;
        } else if (story.status === "reading" && story.pages && story.pages.length > 0) {
          const page = story.pages[story.current_page];
          showPage({
            text: page.text,
            image_b64: page.image_b64,
            image_mime: page.image_mime,
            page: story.current_page,
            total: story.pages.length,
          });
        } else if (story.status === "ready") {
          loadingScreen.querySelector("h1").textContent = "故事準備好了！";
          if (story.title) loadingTitle.textContent = story.title;
        }
      }
    } catch (e) {
      // No story yet
    }

    connectSSE();
  }

  init();
})();
