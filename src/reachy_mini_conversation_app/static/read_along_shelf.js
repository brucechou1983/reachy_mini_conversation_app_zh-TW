(function () {
  var grid = document.getElementById("grid");
  var empty = document.getElementById("empty");

  // Theme-colored placeholder cover when no illustration is cached yet.
  var THEME_EMOJI = {
    "naming emotions": "😊",
    "self-regulation": "🌬️",
    "kindness and empathy": "🤝",
  };

  function coverPlaceholder(book) {
    var div = document.createElement("div");
    div.className = "cover-placeholder";
    div.textContent = THEME_EMOJI[book.sel_theme] || "📖";
    return div;
  }

  function starRow(n) {
    var s = "";
    for (var i = 0; i < n; i++) s += "⭐";
    return s;
  }

  function makeCard(book) {
    var card = document.createElement("button");
    card.className = "book-card2" + (book.completed ? " done" : "");
    card.setAttribute("aria-label", book.title);

    var coverWrap = document.createElement("div");
    coverWrap.className = "cover-wrap";
    if (book.cover_url) {
      var img = document.createElement("img");
      img.className = "cover-img";
      img.src = book.cover_url;
      img.alt = "";
      img.onerror = function () {
        coverWrap.innerHTML = "";
        coverWrap.appendChild(coverPlaceholder(book));
      };
      coverWrap.appendChild(img);
    } else {
      coverWrap.appendChild(coverPlaceholder(book));
    }
    if (book.completed) {
      var check = document.createElement("div");
      check.className = "done-badge";
      check.textContent = "✓";
      coverWrap.appendChild(check);
    }
    card.appendChild(coverWrap);

    var title = document.createElement("div");
    title.className = "card-title";
    title.textContent = book.title;
    card.appendChild(title);

    var meta = document.createElement("div");
    meta.className = "card-meta";
    meta.textContent = book.completed ? "讀過了 " + starRow(book.stars) : "Lv." + book.level;
    card.appendChild(meta);

    card.addEventListener("click", function () {
      select(book, card);
    });
    return card;
  }

  function select(book, card) {
    card.classList.add("selecting");
    fetch("/reader/api/read-along/select", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ book_id: book.id }),
    })
      .then(function (r) {
        return r.ok ? r.json() : { reader_url: "/reader/read-along/" + book.id };
      })
      .then(function (data) {
        location.href = data.reader_url || "/reader/read-along/" + book.id;
      })
      .catch(function () {
        location.href = "/reader/read-along/" + book.id;
      });
  }

  function render(books) {
    grid.setAttribute("aria-busy", "false");
    grid.innerHTML = "";
    if (!books || !books.length) {
      empty.hidden = false;
      return;
    }
    books.forEach(function (b) {
      grid.appendChild(makeCard(b));
    });
  }

  fetch("/reader/api/read-along/books")
    .then(function (r) {
      return r.json();
    })
    .then(render)
    .catch(function () {
      grid.setAttribute("aria-busy", "false");
      empty.hidden = false;
    });
})();
