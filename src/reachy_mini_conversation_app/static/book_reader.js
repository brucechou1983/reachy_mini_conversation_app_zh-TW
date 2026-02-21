(function () {
  // Extract book ID from URL: /reader/books/{book_id}
  var parts = location.pathname.split("/");
  var bookId = parts[parts.length - 1];
  var params = new URLSearchParams(location.search);
  var currentPage = parseInt(params.get("page") || "0", 10);
  var totalPages = 1;

  var pageImage = document.getElementById("page-image");
  var pageText = document.getElementById("page-text");
  var pageNum = document.getElementById("page-num");
  var pageTotal = document.getElementById("page-total");
  var prevBtn = document.getElementById("prev-btn");
  var nextBtn = document.getElementById("next-btn");
  var deleteBtn = document.getElementById("delete-btn");
  var downloadLink = document.getElementById("download-link");
  var readerScreen = document.getElementById("reader-screen");
  var errorScreen = document.getElementById("error-screen");

  function showScreen(screen) {
    document.querySelectorAll(".screen").forEach(function (s) {
      s.classList.remove("active");
    });
    screen.classList.add("active");
  }

  async function loadPage(page) {
    try {
      var resp = await fetch("/reader/api/books/" + bookId + "/pages/" + page);
      if (!resp.ok) {
        showScreen(errorScreen);
        return;
      }
      var data = await resp.json();
      totalPages = data.total;
      currentPage = data.page;

      pageText.textContent = data.text || "";
      pageNum.textContent = (currentPage + 1).toString();
      pageTotal.textContent = totalPages.toString();

      if (data.image_url) {
        pageImage.src = data.image_url;
        pageImage.style.display = "block";
      } else {
        pageImage.src = "";
        pageImage.style.display = "none";
      }

      prevBtn.disabled = currentPage === 0;
      nextBtn.disabled = currentPage >= totalPages - 1;

      // Update URL without reload
      history.replaceState(null, "", "/reader/books/" + bookId + "?page=" + currentPage);

      // Trigger page-turn animation
      var container = document.querySelector(".page-container");
      container.style.animation = "none";
      container.offsetHeight; // trigger reflow
      container.style.animation = "fadeIn 0.5s ease";

      // Track last read (fire-and-forget)
      fetch("/reader/api/books/" + bookId + "/last_read", { method: "POST" });
    } catch (e) {
      console.error("Failed to load page:", e);
      showScreen(errorScreen);
    }
  }

  // Navigation buttons
  prevBtn.addEventListener("click", function () {
    if (currentPage > 0) loadPage(currentPage - 1);
  });
  nextBtn.addEventListener("click", function () {
    if (currentPage < totalPages - 1) loadPage(currentPage + 1);
  });

  // Keyboard navigation
  document.addEventListener("keydown", function (e) {
    if (e.key === "ArrowLeft" && currentPage > 0) loadPage(currentPage - 1);
    if (e.key === "ArrowRight" && currentPage < totalPages - 1) loadPage(currentPage + 1);
  });

  // Delete
  deleteBtn.addEventListener("click", async function () {
    if (!confirm("確定要刪除這本故事書嗎？")) return;
    await fetch("/reader/api/books/" + bookId, { method: "DELETE" });
    location.href = "/reader";
  });

  // Download
  downloadLink.href = "/reader/api/books/" + bookId + "/download";

  // SSE: listen for live page changes from the robot
  var evtSource = null;
  var reconnectAttempts = 0;
  var MAX_RECONNECT = 10;

  function connectSSE() {
    if (evtSource) evtSource.close();
    evtSource = new EventSource("/reader/events");

    evtSource.onopen = function () {
      reconnectAttempts = 0;
    };

    evtSource.onmessage = function (event) {
      try {
        var data = JSON.parse(event.data);
        if (data.event === "page_change") {
          // Robot turned a page — reload via REST to get the image URL
          loadPage(data.page);
        } else if (data.event === "story_closed") {
          // Robot closed the story; stay on current page (user can still browse)
        }
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

  // Initialize
  showScreen(readerScreen);
  loadPage(currentPage);
  connectSSE();
})();
