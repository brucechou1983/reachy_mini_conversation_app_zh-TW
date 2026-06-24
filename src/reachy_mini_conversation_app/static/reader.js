(function () {
  var grid = document.getElementById("book-grid");
  var emptyShelf = document.getElementById("empty-shelf");

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  async function loadBookshelf() {
    try {
      var resp = await fetch("/reader/api/books");
      if (!resp.ok) throw new Error("server error");
      var books = await resp.json();
      renderGrid(books);
    } catch (e) {
      console.error("Failed to load bookshelf:", e);
    }
  }

  function renderGrid(books) {
    grid.innerHTML = "";
    if (books.length === 0) {
      emptyShelf.classList.remove("hidden");
      return;
    }
    emptyShelf.classList.add("hidden");

    books.forEach(function (book) {
      var card = document.createElement("div");
      card.className = "book-card";

      var safeTitle = escapeHtml(book.title);
      var safeId = encodeURIComponent(book.id);

      var coverHtml = book.cover_url
        ? '<img class="book-cover" src="' + book.cover_url + '" alt="' + safeTitle + '" />'
        : '<div class="book-cover-placeholder">📖</div>';

      card.innerHTML =
        '<a href="/reader/books/' + safeId + '" class="book-cover-link" data-id="' + escapeHtml(book.id) + '">' +
          coverHtml +
          '<div class="book-title">' + safeTitle + "</div>" +
          '<div class="book-meta">' + book.page_count + " 頁</div>" +
        "</a>" +
        '<div class="book-card-actions">' +
          '<a class="book-action-btn" href="/reader/api/books/' + safeId + '/download" title="下載">⬇</a>' +
          '<button class="book-action-btn danger delete-book-btn" data-id="' + safeId + '" title="刪除">✕</button>' +
        "</div>";

      grid.appendChild(card);
    });

    grid.querySelectorAll(".delete-book-btn").forEach(function (btn) {
      btn.addEventListener("click", async function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (!confirm("確定要刪除這本故事書嗎？")) return;
        var id = btn.dataset.id;
        await fetch("/reader/api/books/" + id, { method: "DELETE" });
        loadBookshelf();
      });
    });

    // Tapping a cover: tell the robot to open & read this book, then show it.
    grid.querySelectorAll(".book-cover-link").forEach(function (link) {
      link.addEventListener("click", function (e) {
        e.preventDefault();
        var id = link.dataset.id;
        var dest = "/reader/books/" + encodeURIComponent(id);
        fetch("/reader/api/books/" + encodeURIComponent(id) + "/select", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        })
          .catch(function () {})           // robot may be offline; still open the book
          .finally(function () {
            location.href = dest;
          });
      });
    });
  }

  loadBookshelf();
})();
