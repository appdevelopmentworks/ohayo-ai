// おはようAI — progressive enhancement only. Every page is complete without this file.
(function () {
  "use strict";

  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  function each(list, fn) {
    Array.prototype.forEach.call(list, fn);
  }

  function storageGet(key) {
    try {
      return window.localStorage.getItem(key);
    } catch (e) {
      return null;
    }
  }

  function storageSet(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      /* private mode or blocked storage: the streak simply is not counted */
    }
  }

  // Category tabs: filter the pre-rendered cards, reordering with View Transitions when available.
  function setupTabs() {
    var nav = document.querySelector(".tabs");
    if (!nav) return;
    var cards = document.querySelectorAll(".card[data-tabs]");
    var empty = document.querySelector(".empty");
    var emptyLabel = empty && empty.querySelector(".empty-label");
    nav.hidden = false;

    function apply(button) {
      var key = button.getAttribute("data-tab");
      var shown = 0;
      each(nav.querySelectorAll(".tab"), function (tab) {
        tab.setAttribute("aria-pressed", tab === button ? "true" : "false");
      });
      each(cards, function (card) {
        var match = (" " + card.getAttribute("data-tabs") + " ").indexOf(" " + key + " ") !== -1;
        card.hidden = !match;
        if (match) {
          shown += 1;
          card.classList.add("is-in");
        }
      });
      if (empty) {
        empty.hidden = shown > 0;
        if (emptyLabel) emptyLabel.textContent = button.firstChild.textContent.trim();
      }
    }

    nav.addEventListener("click", function (event) {
      var button = event.target.closest(".tab");
      if (!button || button.getAttribute("aria-pressed") === "true") return;
      // Background tabs never paint, so a transition there would hold the update back.
      if (document.startViewTransition && !reduceMotion && document.visibilityState === "visible") {
        document.startViewTransition(function () {
          apply(button);
        });
      } else {
        apply(button);
      }
    });
  }

  // Glossary memo: open a bottom sheet instead of expanding the <details> in place.
  function setupTermSheet() {
    var sheet = document.getElementById("term-sheet");
    if (!sheet || typeof sheet.showModal !== "function") return; // keep the <details> fallback
    var word = sheet.querySelector(".sheet-word");
    var note = sheet.querySelector(".sheet-note");
    var opener = null;

    document.addEventListener("click", function (event) {
      var summary = event.target.closest(".term summary");
      if (!summary) return;
      event.preventDefault();
      var details = summary.parentElement;
      word.textContent = details.getAttribute("data-word");
      note.textContent = details.getAttribute("data-note");
      opener = summary;
      sheet.showModal();
    });

    sheet.addEventListener("click", function (event) {
      if (event.target === sheet) sheet.close(); // tap on the dimmed backdrop
    });
    sheet.addEventListener("close", function () {
      if (opener) opener.focus();
    });
  }

  // Cards fade in from below as they scroll into view. Cards already on screen stay put,
  // so nothing the reader can see disappears when the script starts.
  function setupCardReveal() {
    var cards = document.querySelectorAll(".card");
    each(cards, function (card) {
      if (card.getBoundingClientRect().top < window.innerHeight) card.classList.add("is-in", "is-static");
    });
    if (!("IntersectionObserver" in window)) {
      each(cards, function (card) {
        card.classList.add("is-in", "is-static");
      });
      return;
    }
    document.documentElement.classList.add("js-ready");
    var observer = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (entry) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-in");
            observer.unobserve(entry.target);
          }
        });
      },
      { rootMargin: "0px 0px -8% 0px" }
    );
    each(cards, function (card) {
      observer.observe(card);
    });
  }

  // Reading streak: days in a row on which the reader reached the end of the morning page.
  function nextStreak(editionDate) {
    var saved = {};
    try {
      saved = JSON.parse(storageGet("ohayo-ai:streak") || "{}") || {};
    } catch (e) {
      saved = {};
    }
    var count = 1;
    if (saved.last === editionDate) {
      count = saved.count || 1;
    } else if (saved.last) {
      var gap = (Date.parse(editionDate) - Date.parse(saved.last)) / 86400000;
      if (gap === 1) count = (saved.count || 0) + 1;
    }
    storageSet("ohayo-ai:streak", JSON.stringify({ last: editionDate, count: count }));
    return count;
  }

  function setupFinish() {
    var layout = document.querySelector("[data-edition-date]");
    var finish = document.querySelector(".finish:not(.finish--archive)");
    if (!layout || !finish) return;
    var editionDate = layout.getAttribute("data-edition-date");

    function done() {
      finish.classList.add("is-done");
      var streak = finish.querySelector(".streak");
      if (streak) {
        streak.querySelector("[data-streak]").textContent = String(nextStreak(editionDate));
        streak.hidden = false;
      }
    }

    if (!("IntersectionObserver" in window)) return;
    var observer = new IntersectionObserver(
      function (entries) {
        if (entries.some(function (entry) { return entry.isIntersecting; })) {
          observer.disconnect();
          done();
        }
      },
      { threshold: 0.4 }
    );
    observer.observe(finish);
  }

  function init() {
    setupTabs();
    setupTermSheet();
    setupCardReveal();
    setupFinish();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
