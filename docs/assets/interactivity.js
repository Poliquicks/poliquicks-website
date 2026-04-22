// Replaces pieces of Squarespace-runtime behavior we stripped. All targets
// reuse the class/attribute conventions Squarespace's CSS already keys off,
// so the existing styles do the visual work once state is toggled.
(function () {
  "use strict";

  // --- Hamburger -----------------------------------------------------------
  function setMenuOpen(button, open) {
    document.body.classList.toggle("header--menu-open", open);
    button.classList.toggle("burger--active", open);
    button.setAttribute("aria-expanded", open ? "true" : "false");
  }

  document.querySelectorAll(".header-burger-btn").forEach(function (btn) {
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var isOpen = document.body.classList.contains("header--menu-open");
      setMenuOpen(btn, !isOpen);
    });
  });

  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    if (!document.body.classList.contains("header--menu-open")) return;
    var btn = document.querySelector(".header-burger-btn");
    if (btn) setMenuOpen(btn, false);
  });

  // --- Accordion -----------------------------------------------------------
  // Squarespace animates the dropdown's height from 0 → content height. Since
  // CSS can't animate `height: auto`, we measure scrollHeight on expand and
  // set it explicitly, then clear it after the transition so the panel can
  // reflow naturally on resize.
  document.querySelectorAll(".accordion-item__dropdown").forEach(function (d) {
    d.style.transition = "height 320ms cubic-bezier(.4,0,.2,1)";
    d.style.height = "0px";
    d.style.display = "block";
    d.style.overflow = "hidden";
  });

  document.querySelectorAll(".accordion-item__click-target").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var item = btn.closest(".accordion-item");
      if (!item) return;
      var dropdown = item.querySelector(".accordion-item__dropdown");
      var icon = item.querySelector(".accordion-icon-container");
      var open = btn.getAttribute("aria-expanded") !== "true";
      btn.setAttribute("aria-expanded", open ? "true" : "false");
      if (icon) icon.setAttribute("data-is-open", open ? "true" : "false");
      item.setAttribute("data-is-open", open ? "true" : "false");
      if (!dropdown) return;

      if (open) {
        dropdown.classList.add("accordion-item__dropdown--open");
        var target = dropdown.scrollHeight;
        dropdown.style.height = target + "px";
        var onEnd = function () {
          dropdown.style.height = "auto";
          dropdown.removeEventListener("transitionend", onEnd);
        };
        dropdown.addEventListener("transitionend", onEnd);
      } else {
        // Lock current pixel height so the transition has something to go from
        dropdown.style.height = dropdown.scrollHeight + "px";
        // Force reflow so the browser picks up the fixed height before we drop it
        void dropdown.offsetHeight;
        dropdown.style.height = "0px";
        dropdown.classList.remove("accordion-item__dropdown--open");
      }
    });
  });

  // --- Marquee -------------------------------------------------------------
  // Squarespace's Marquee block renders text along an SVG path that their JS
  // runtime computes on the fly. Without the runtime, the visible SVG is empty.
  // We replace the Marquee-display contents with a CSS-animated strip of
  // duplicated copies of the source text so it loops across the viewport.
  document.querySelectorAll(".Marquee").forEach(function (marquee) {
    var measure = marquee.querySelector(".Marquee-measure");
    var display = marquee.querySelector(".Marquee-display");
    if (!measure || !display) return;

    var items = Array.from(measure.querySelectorAll(".Marquee-item"));
    if (!items.length) return;

    // Duplicate enough items to span well beyond the viewport — 16 copies of
    // "Download Now!" @ ~300px per copy gives us ~4800px, enough for any screen.
    var REPEATS = 16;
    var group = document.createElement("div");
    group.className = "marquee-shim-group";
    for (var i = 0; i < REPEATS; i++) {
      items.forEach(function (it) { group.appendChild(it.cloneNode(true)); });
    }

    var track = document.createElement("div");
    track.className = "marquee-shim-track";
    // Two copies of the fully-duplicated group — the keyframe shifts by 50%
    // exactly, so as soon as copy #1 is off-screen-left, copy #2 is in place
    // and the jump back to 0 is invisible.
    track.appendChild(group);
    track.appendChild(group.cloneNode(true));

    var linkTo = marquee.getAttribute("data-link-to");
    if (linkTo) {
      var a = document.createElement("a");
      a.href = linkTo;
      a.rel = "noopener";
      if (marquee.getAttribute("data-new-window") === "true") a.target = "_blank";
      a.style.display = "block";
      a.style.color = "inherit";
      a.style.textDecoration = "inherit";
      a.appendChild(track);
      display.innerHTML = "";
      display.appendChild(a);
    } else {
      display.innerHTML = "";
      display.appendChild(track);
    }
  });

  // --- Formspree AJAX submit ----------------------------------------------
  // Submit the contact + newsletter forms in-page so there's no redirect to
  // formspree.io's thank-you screen. Formspree returns JSON when we set
  // `Accept: application/json`, so we can show an inline success/error message
  // and reset the form.
  function wireFormspreeForm(form, options) {
    options = options || {};
    form.addEventListener("submit", async function (e) {
      if (!form.action || form.action.indexOf("formspree.io") === -1) return;
      e.preventDefault();

      var submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
      var originalLabel = submitBtn ? submitBtn.textContent : null;
      if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = "Sending..."; }

      try {
        var resp = await fetch(form.action, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        if (resp.ok) {
          options.onSuccess && options.onSuccess(form);
        } else {
          var data = {};
          try { data = await resp.json(); } catch (_) {}
          var msg = (data.errors && data.errors.map(function (x) { return x.message; }).join(", "))
            || "Something went wrong. Please try again.";
          options.onError && options.onError(form, msg);
        }
      } catch (err) {
        options.onError && options.onError(form, "Network error. Please try again.");
      } finally {
        if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = originalLabel; }
      }
    });
  }

  // Contact form ("Get in touch") — show inline status, reset on success.
  document.querySelectorAll("form.contact-form-shim").forEach(function (form) {
    var status = form.querySelector(".contact-form-shim__status");
    wireFormspreeForm(form, {
      onSuccess: function () {
        form.reset();
        if (status) { status.textContent = "Thank you! Your message was sent."; status.style.color = "#7a2ec4"; }
      },
      onError: function (_f, msg) {
        if (status) { status.textContent = msg; status.style.color = "#b33"; }
      },
    });
  });

  // Footer newsletter form — no dedicated status element; replace the form
  // body with a thank-you message on success.
  document.querySelectorAll("form.site-footer__newsletter-form").forEach(function (form) {
    wireFormspreeForm(form, {
      onSuccess: function () {
        form.innerHTML = '<span style="color:#fff;font-weight:600;">Thanks for subscribing!</span>';
      },
      onError: function (f, msg) {
        var err = f.querySelector(".site-footer__newsletter-error");
        if (!err) {
          err = document.createElement("div");
          err.className = "site-footer__newsletter-error";
          err.style.cssText = "grid-column: 1 / -1; color: #ffd; font-size: 0.85rem; margin-top: 6px;";
          f.appendChild(err);
        }
        err.textContent = msg;
      },
    });
  });

  // --- Carousel (Meet the Team) -------------------------------------------
  // Arrow-controlled horizontal scroller with seamless infinite wrap. We clone
  // the slide set twice (total 3 copies) and start scrolled into the middle
  // copy. On scroll, if we drift into the first or last copy we instantly
  // teleport one set-width over — since the three copies are identical, the
  // jump is invisible. Arrows trigger a smooth scrollBy(one slide).
  document.querySelectorAll(".user-items-list-carousel").forEach(function (root) {
    var slides = root.querySelector(".user-items-list-carousel__slides");
    if (!slides) return;

    var originals = Array.from(slides.querySelectorAll(".user-items-list-carousel__slide"));
    if (!originals.length) return;

    var GAP_PX = 32;

    // Undo Squarespace's grid layout and opacity-0 wrapper state
    slides.style.display = "flex";
    slides.style.flexWrap = "nowrap";
    slides.style.opacity = "1";
    slides.style.gap = GAP_PX + "px";
    slides.style.overflowX = "auto";
    slides.style.overflowY = "hidden";
    slides.style.scrollBehavior = "smooth";
    slides.style.scrollbarWidth = "none"; // Firefox
    slides.classList.add("team-carousel-no-scrollbar");

    originals.forEach(function (s) {
      s.style.transform = "none";
      s.style.pointerEvents = "auto";
      s.style.userSelect = "auto";
      s.style.flex = "0 0 auto";
      s.style.width = "min(380px, 78vw)";
      s.style.gridColumnStart = "auto";
      s.style.gridRowStart = "auto";
    });

    // Clone twice → three identical copies of the set
    for (var i = 0; i < 2; i++) {
      originals.forEach(function (s) {
        var clone = s.cloneNode(true);
        clone.setAttribute("aria-hidden", "true");
        slides.appendChild(clone);
      });
    }

    // Start scrolled to the middle copy so we can wrap in either direction.
    // scrollWidth/3 = one set's width; add scroll snap for crisp arrow stops.
    function setWidth() { return slides.scrollWidth / 3; }
    function alignToMiddle() { slides.scrollLeft = setWidth(); }
    // Defer one frame so layout has settled before we read scrollWidth
    requestAnimationFrame(alignToMiddle);
    window.addEventListener("resize", alignToMiddle);

    // Teleport near the edges — done during scroll, masked by identical content
    var teleporting = false;
    slides.addEventListener("scroll", function () {
      if (teleporting) return;
      var w = setWidth();
      if (slides.scrollLeft < w * 0.5) {
        teleporting = true;
        var prevBehavior = slides.style.scrollBehavior;
        slides.style.scrollBehavior = "auto";
        slides.scrollLeft += w;
        slides.style.scrollBehavior = prevBehavior;
        teleporting = false;
      } else if (slides.scrollLeft > w * 1.5) {
        teleporting = true;
        var prev = slides.style.scrollBehavior;
        slides.style.scrollBehavior = "auto";
        slides.scrollLeft -= w;
        slides.style.scrollBehavior = prev;
        teleporting = false;
      }
    });

    function step(direction) {
      var first = slides.querySelector(".user-items-list-carousel__slide");
      var delta = first ? first.getBoundingClientRect().width + GAP_PX : slides.clientWidth * 0.6;
      slides.scrollBy({ left: direction * delta, behavior: "smooth" });
    }

    root.querySelectorAll(".user-items-list-carousel__arrow-button--left").forEach(function (b) {
      b.addEventListener("click", function () { step(-1); });
    });
    root.querySelectorAll(".user-items-list-carousel__arrow-button--right").forEach(function (b) {
      b.addEventListener("click", function () { step(1); });
    });
    // Make sure the arrow wrappers are visible (previous version hid them)
    root.querySelectorAll(".user-items-list-carousel__arrow-wrapper").forEach(function (w) {
      w.style.display = "";
    });

    // Click-and-drag panning. Touch already scrolls natively because the
    // container is overflow:auto; this adds the equivalent for mouse.
    // Drag distance > 5px suppresses click-through on links inside slides.
    var dragging = false;
    var dragStartX = 0;
    var dragStartScroll = 0;
    var dragMoved = 0;

    slides.addEventListener("mousedown", function (e) {
      // Ignore clicks on arrow buttons (they handle their own events)
      if (e.target.closest(".user-items-list-carousel__arrow-button")) return;
      dragging = true;
      dragMoved = 0;
      dragStartX = e.clientX;
      dragStartScroll = slides.scrollLeft;
      slides.style.scrollBehavior = "auto";
      slides.style.cursor = "grabbing";
      // Prevent native image drag-and-drop
      e.preventDefault();
    });

    window.addEventListener("mousemove", function (e) {
      if (!dragging) return;
      var dx = e.clientX - dragStartX;
      dragMoved = Math.max(dragMoved, Math.abs(dx));
      slides.scrollLeft = dragStartScroll - dx;
    });

    function endDrag() {
      if (!dragging) return;
      dragging = false;
      slides.style.scrollBehavior = "smooth";
      slides.style.cursor = "";
    }
    window.addEventListener("mouseup", endDrag);
    window.addEventListener("mouseleave", endDrag);

    // Swallow the click that follows a drag of more than a few pixels, so
    // users don't accidentally trigger link navigation when they meant to pan.
    slides.addEventListener("click", function (e) {
      if (dragMoved > 5) { e.preventDefault(); e.stopPropagation(); }
    }, true);

    slides.style.cursor = "grab";
    // Keep the slides' native `::-webkit-scrollbar` hidden (CSS handles that),
    // and disable the browser's "drag the image to another tab" affordance.
    slides.querySelectorAll("img").forEach(function (img) {
      img.setAttribute("draggable", "false");
    });
  });
})();
