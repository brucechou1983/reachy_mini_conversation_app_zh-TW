(function () {
  var grid = document.getElementById("book-grid");
  var emptyShelf = document.getElementById("empty-shelf");

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

      var coverHtml = book.cover_url
        ? '<img class="book-cover" src="' + book.cover_url + '" alt="' + book.title + '" />'
        : '<div class="book-cover-placeholder">📖</div>';

      card.innerHTML =
        '<a href="/reader/books/' + book.id + '" class="book-cover-link">' +
          coverHtml +
          '<div class="book-title">' + book.title + "</div>" +
          '<div class="book-meta">' + book.page_count + " 頁</div>" +
        "</a>" +
        '<div class="book-card-actions">' +
          '<a class="book-action-btn" href="/reader/api/books/' + book.id + '/download" title="下載">⬇</a>' +
          '<button class="book-action-btn danger delete-book-btn" data-id="' + book.id + '" title="刪除">✕</button>' +
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
  }

  loadBookshelf();
})();
