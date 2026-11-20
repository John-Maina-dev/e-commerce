/* ============================================================================
   Reeves Boutique — Storefront Product Animations Controller
   Vanilla JavaScript (zero dependencies), GPU-friendly, accessible,
   respects prefers-reduced-motion, tab visibility, and Store Settings toggles.
   ============================================================================ */
(function () {
  'use strict';

  var body = document.body;
  var animationsDisabledByAdmin = body && body.getAttribute('data-animations') === 'off';
  var speedPreset = (body && body.getAttribute('data-anim-speed')) || 'normal';
  var reducedMotionQuery = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;

  var SPEED_MAP = {
    slow: { heroMs: 8500, coverflowMs: 5600, spinMs: 180, marqueeSecPerItem: 6.2 },
    normal: { heroMs: 6000, coverflowMs: 4000, spinMs: 120, marqueeSecPerItem: 4.2 },
    fast: { heroMs: 4200, coverflowMs: 2800, spinMs: 80, marqueeSecPerItem: 2.8 }
  };
  var timing = SPEED_MAP[speedPreset] || SPEED_MAP.normal;

  function prefersReducedMotion() {
    return animationsDisabledByAdmin || Boolean(reducedMotionQuery && reducedMotionQuery.matches);
  }

  /* --------------------------------------------------------------------------
     1. HERO SHOWCASE SLIDER (Ken Burns crossfade, dots, arrows, swipe, pause)
     -------------------------------------------------------------------------- */
  function initHeroSliders() {
    document.querySelectorAll('[data-hero-slider]').forEach(function (root) {
      var slides = Array.prototype.slice.call(root.querySelectorAll('.rb-hero-slide'));
      if (slides.length <= 1) return;

      var dots = Array.prototype.slice.call(root.querySelectorAll('[data-hero-dot]'));
      var prevBtn = root.querySelector('[data-hero-prev]');
      var nextBtn = root.querySelector('[data-hero-next]');
      var pauseBtn = root.querySelector('[data-hero-pause]');
      var counter = root.querySelector('[data-hero-counter]');

      var current = 0;
      var timer = null;
      var userPaused = false;
      var hovered = false;
      var touchStartX = null;

      function pad(n) { return n < 10 ? '0' + n : '' + n; }

      function goTo(index) {
        var nextIdx = ((index % slides.length) + slides.length) % slides.length;
        if (nextIdx === current) return;

        slides[current].classList.remove('is-active');
        slides[current].setAttribute('aria-hidden', 'true');
        var prevFrame = slides[current].querySelector('.rb-hero-frame');
        if (prevFrame) prevFrame.setAttribute('tabindex', '-1');

        slides[nextIdx].classList.add('is-active');
        slides[nextIdx].setAttribute('aria-hidden', 'false');
        var nextFrame = slides[nextIdx].querySelector('.rb-hero-frame');
        if (nextFrame) nextFrame.setAttribute('tabindex', '0');

        dots.forEach(function (d, i) {
          var active = i === nextIdx;
          d.classList.toggle('is-active', active);
          d.setAttribute('aria-selected', active ? 'true' : 'false');
          // Restart dot progress bar animation cleanly
          var bar = d.querySelector('.rb-hero-dot-progress');
          if (bar) {
            bar.style.animation = 'none';
            void bar.offsetWidth;
            bar.style.animation = '';
          }
        });

        if (counter) {
          counter.textContent = pad(nextIdx + 1) + ' / ' + pad(slides.length);
        }
        current = nextIdx;
      }

      function stopTimer() {
        if (timer) {
          clearInterval(timer);
          timer = null;
        }
      }

      function startTimer() {
        stopTimer();
        if (userPaused || hovered || document.hidden || prefersReducedMotion()) {
          root.classList.add('is-paused');
          return;
        }
        root.classList.remove('is-paused');
        timer = setInterval(function () {
          goTo(current + 1);
        }, timing.heroMs);
      }

      if (prevBtn) prevBtn.addEventListener('click', function () { goTo(current - 1); startTimer(); });
      if (nextBtn) nextBtn.addEventListener('click', function () { goTo(current + 1); startTimer(); });

      dots.forEach(function (d, idx) {
        d.addEventListener('click', function () { goTo(idx); startTimer(); });
      });

      if (pauseBtn) {
        pauseBtn.addEventListener('click', function () {
          userPaused = !userPaused;
          pauseBtn.setAttribute('aria-pressed', userPaused ? 'true' : 'false');
          pauseBtn.setAttribute('aria-label', userPaused ? 'Resume showcase rotation' : 'Pause showcase rotation');
          root.classList.toggle('is-user-paused', userPaused);
          startTimer();
        });
      }

      root.addEventListener('mouseenter', function () { hovered = true; stopTimer(); });
      root.addEventListener('mouseleave', function () { hovered = false; startTimer(); });
      root.addEventListener('focusin', function () { hovered = true; stopTimer(); });
      root.addEventListener('focusout', function (e) {
        if (!root.contains(e.relatedTarget)) { hovered = false; startTimer(); }
      });

      root.addEventListener('touchstart', function (e) {
        if (e.touches && e.touches.length) touchStartX = e.touches[0].clientX;
        stopTimer();
      }, { passive: true });

      root.addEventListener('touchend', function (e) {
        if (touchStartX !== null && e.changedTouches && e.changedTouches.length) {
          var dx = e.changedTouches[0].clientX - touchStartX;
          if (Math.abs(dx) > 45) {
            goTo(dx < 0 ? current + 1 : current - 1);
          }
        }
        touchStartX = null;
        startTimer();
      }, { passive: true });

      root.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(current - 1); startTimer(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(current + 1); startTimer(); }
      });

      document.addEventListener('visibilitychange', function () {
        if (document.hidden) stopTimer();
        else startTimer();
      });

      if (reducedMotionQuery && reducedMotionQuery.addEventListener) {
        reducedMotionQuery.addEventListener('change', startTimer);
      }

      startTimer();
    });
  }

  /* --------------------------------------------------------------------------
     2. 3D ROTATING COVERFLOW CAROUSEL (Ring math, drag/swipe, click-to-focus)
     -------------------------------------------------------------------------- */
  function initCoverflows() {
    document.querySelectorAll('[data-coverflow]').forEach(function (root) {
      var stage = root.querySelector('.rb-cf-stage');
      var slides = Array.prototype.slice.call(root.querySelectorAll('.rb-cf-slide'));
      if (!stage || !slides.length) return;

      var dots = Array.prototype.slice.call(root.querySelectorAll('[data-cf-dot]'));
      var prevBtn = root.querySelector('[data-cf-prev]');
      var nextBtn = root.querySelector('[data-cf-next]');

      var total = slides.length;
      var active = 0;
      var timer = null;
      var paused = false;
      var dragStartX = null;
      var dragMoved = false;

      function shortestOffset(idx, center, len) {
        var diff = idx - center;
        if (len <= 2) return diff;
        var half = Math.floor(len / 2);
        if (diff > half) diff -= len;
        if (diff < -half) diff += len;
        return diff;
      }

      function layout() {
        var stageWidth = stage.clientWidth || 960;
        var spacing = Math.min(265, Math.max(150, stageWidth * 0.27));
        var isSmall = stageWidth < 640;

        slides.forEach(function (slide, idx) {
          var offset = shortestOffset(idx, active, total);
          var abs = Math.abs(offset);
          var isCenter = offset === 0;

          slide.classList.toggle('is-center', isCenter);
          slide.setAttribute('aria-hidden', abs > 2 ? 'true' : 'false');

          if (abs > 2) {
            slide.style.opacity = '0';
            slide.style.pointerEvents = 'none';
            slide.style.zIndex = '0';
            slide.style.transform = 'translate3d(-50%, -50%, -340px) scale(0.62)';
            slide.style.filter = 'blur(4px)';
            return;
          }

          var tx = offset * (isSmall ? spacing * 0.78 : spacing);
          var tz = isCenter ? 0 : (abs === 1 ? -145 : -260);
          var rotY = isCenter ? 0 : (offset > 0 ? (abs === 1 ? -28 : -44) : (abs === 1 ? 28 : 44));
          var sc = isCenter ? 1 : (abs === 1 ? 0.85 : 0.72);
          var op = isCenter ? 1 : (abs === 1 ? (isSmall ? 0.55 : 0.78) : (isSmall ? 0.12 : 0.4));
          var blurPx = isCenter ? 0 : (abs === 1 ? 1.4 : 2.8);

          slide.style.transform =
            'translate3d(calc(-50% + ' + tx.toFixed(1) + 'px), -50%, ' + tz + 'px) ' +
            'rotateY(' + rotY + 'deg) scale(' + sc + ')';
          slide.style.opacity = String(op);
          slide.style.filter = blurPx ? 'blur(' + blurPx + 'px)' : 'none';
          slide.style.zIndex = String(10 - abs * 3);
          slide.style.pointerEvents = 'auto';
        });

        dots.forEach(function (d, i) {
          var on = i === active;
          d.classList.toggle('is-active', on);
          d.setAttribute('aria-selected', on ? 'true' : 'false');
        });
      }

      function goTo(index) {
        if (total <= 1) return;
        active = ((index % total) + total) % total;
        layout();
      }

      function stopAuto() {
        if (timer) { clearInterval(timer); timer = null; }
      }

      function startAuto() {
        stopAuto();
        if (total <= 1 || paused || document.hidden || prefersReducedMotion()) return;
        timer = setInterval(function () { goTo(active + 1); }, timing.coverflowMs);
      }

      // Click any non-center slide to rotate it to center
      slides.forEach(function (slide, idx) {
        slide.addEventListener('click', function (e) {
          if (dragMoved) { e.preventDefault(); return; }
          if (idx !== active) {
            e.preventDefault();
            goTo(idx);
            startAuto();
          }
        });
      });

      if (prevBtn) prevBtn.addEventListener('click', function () { goTo(active - 1); startAuto(); });
      if (nextBtn) nextBtn.addEventListener('click', function () { goTo(active + 1); startAuto(); });
      dots.forEach(function (d, i) {
        d.addEventListener('click', function () { goTo(i); startAuto(); });
      });

      // Pointer drag & touch swipe
      stage.addEventListener('pointerdown', function (e) {
        if (total <= 1 || e.target.closest('button, a')) return;
        dragStartX = e.clientX;
        dragMoved = false;
        stage.classList.add('is-dragging');
        stopAuto();
      });

      window.addEventListener('pointermove', function (e) {
        if (dragStartX === null) return;
        if (Math.abs(e.clientX - dragStartX) > 10) dragMoved = true;
      });

      window.addEventListener('pointerup', function (e) {
        if (dragStartX === null) return;
        var dx = e.clientX - dragStartX;
        dragStartX = null;
        stage.classList.remove('is-dragging');
        if (Math.abs(dx) > 42) {
          goTo(dx < 0 ? active + 1 : active - 1);
        }
        setTimeout(function () { dragMoved = false; }, 50);
        startAuto();
      });

      // Touch swipe fallback for links inside stage on mobile
      var touchX = null;
      stage.addEventListener('touchstart', function (e) {
        if (e.touches && e.touches.length) touchX = e.touches[0].clientX;
        stopAuto();
      }, { passive: true });
      stage.addEventListener('touchend', function (e) {
        if (touchX !== null && e.changedTouches && e.changedTouches.length) {
          var dx = e.changedTouches[0].clientX - touchX;
          if (Math.abs(dx) > 42) goTo(dx < 0 ? active + 1 : active - 1);
        }
        touchX = null;
        startAuto();
      }, { passive: true });

      root.addEventListener('mouseenter', function () { paused = true; stopAuto(); });
      root.addEventListener('mouseleave', function () { paused = false; startAuto(); });
      root.addEventListener('focusin', function () { paused = true; stopAuto(); });
      root.addEventListener('focusout', function (e) {
        if (!root.contains(e.relatedTarget)) { paused = false; startAuto(); }
      });

      root.addEventListener('keydown', function (e) {
        if (e.key === 'ArrowLeft') { e.preventDefault(); goTo(active - 1); startAuto(); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); goTo(active + 1); startAuto(); }
      });

      window.addEventListener('resize', layout);
      document.addEventListener('visibilitychange', function () {
        if (document.hidden) stopAuto();
        else startAuto();
      });

      layout();
      startAuto();
    });
  }

  /* --------------------------------------------------------------------------
     3. INFINITE MARQUEE STRIP (Seamless loop, hover/touch/tab pause)
     -------------------------------------------------------------------------- */
  function initMarquees() {
    document.querySelectorAll('[data-marquee]').forEach(function (viewport) {
      var track = viewport.querySelector('[data-marquee-track]');
      var group = viewport.querySelector('[data-marquee-group]');
      if (!track || !group) return;

      var items = group.querySelectorAll('.rb-marquee-item');
      if (items.length < 2 || prefersReducedMotion()) {
        viewport.classList.add('is-static');
        return;
      }

      // Clone group once for seamless -50% infinite loop; hide clone from AT & tab order
      var clone = group.cloneNode(true);
      clone.setAttribute('aria-hidden', 'true');
      clone.removeAttribute('data-marquee-group');
      clone.querySelectorAll('a, button, input, select, textarea').forEach(function (el) {
        el.setAttribute('tabindex', '-1');
      });
      track.appendChild(clone);

      // Scale duration proportionally so scroll speed feels consistent regardless of item count
      var seconds = Math.max(18, Math.round(items.length * timing.marqueeSecPerItem));
      viewport.style.setProperty('--rb-marquee-duration', seconds + 's');
      viewport.classList.add('is-animated');

      // Pause on touch and when browser tab is hidden
      viewport.addEventListener('touchstart', function () {
        viewport.classList.add('is-paused');
      }, { passive: true });
      viewport.addEventListener('touchend', function () {
        setTimeout(function () { viewport.classList.remove('is-paused'); }, 1200);
      }, { passive: true });

      document.addEventListener('visibilitychange', function () {
        viewport.classList.toggle('is-paused', document.hidden);
      });
    });
  }

  /* --------------------------------------------------------------------------
     4. 3D TILT PRODUCT CARDS & WISHLIST HEART POP
     -------------------------------------------------------------------------- */
  function initTiltCards() {
    var finePointer = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;

    if (finePointer && !prefersReducedMotion()) {
      var maxDeg = 7.5;
      document.addEventListener('mousemove', function (e) {
        var card = e.target.closest ? e.target.closest('[data-tilt-card]') : null;
        if (!card) return;
        if (card._rbRaf) return;
        card._rbRaf = requestAnimationFrame(function () {
          card._rbRaf = null;
          var rect = card.getBoundingClientRect();
          if (!rect.width || !rect.height) return;
          var px = (e.clientX - rect.left) / rect.width;
          var py = (e.clientY - rect.top) / rect.height;
          var rotY = (px - 0.5) * (maxDeg * 2);
          var rotX = (0.5 - py) * (maxDeg * 2);
          card.style.setProperty('--tilt-x', rotX.toFixed(2) + 'deg');
          card.style.setProperty('--tilt-y', rotY.toFixed(2) + 'deg');
          card.style.setProperty('--glare-x', (px * 100).toFixed(1) + '%');
          card.style.setProperty('--glare-y', (py * 100).toFixed(1) + '%');
          card.style.setProperty('--glare-opacity', '1');
        });
      }, { passive: true });

      document.addEventListener('mouseout', function (e) {
        var card = e.target.closest ? e.target.closest('[data-tilt-card]') : null;
        if (!card) return;
        if (e.relatedTarget && card.contains(e.relatedTarget)) return;
        card.style.setProperty('--tilt-x', '0deg');
        card.style.setProperty('--tilt-y', '0deg');
        card.style.setProperty('--glare-opacity', '0');
      });
    }

    // Wishlist heart spring pop on click
    document.addEventListener('click', function (e) {
      var wishBtn = e.target.closest ? e.target.closest('[data-wish-btn]') : null;
      if (!wishBtn) return;
      wishBtn.classList.remove('is-popping');
      void wishBtn.offsetWidth;
      wishBtn.classList.add('is-popping');
    });
  }

  /* --------------------------------------------------------------------------
     5. SCROLL-REVEAL STAGGERED GRID (IntersectionObserver)
     -------------------------------------------------------------------------- */
  function initScrollReveal() {
    var grids = document.querySelectorAll('[data-reveal-grid]');
    if (!grids.length) return;

    if (prefersReducedMotion() || !('IntersectionObserver' in window)) {
      grids.forEach(function (g) {
        g.querySelectorAll('[data-reveal-item]').forEach(function (item) {
          item.classList.add('is-revealed');
        });
      });
      return;
    }

    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-revealed');
          observer.unobserve(entry.target);
        }
      });
    }, { rootMargin: '0px 0px -40px 0px', threshold: 0.06 });

    grids.forEach(function (grid) {
      grid.classList.add('rb-reveal-armed');
      grid.querySelectorAll('[data-reveal-item]').forEach(function (item) {
        observer.observe(item);
      });
    });
  }

  /* --------------------------------------------------------------------------
     6. PRODUCT DETAIL GALLERY — Smooth Zoom + Interactive 360° Spin
     -------------------------------------------------------------------------- */
  function initProductGalleries() {
    document.querySelectorAll('[data-product-gallery]').forEach(function (root) {
      var stage = root.querySelector('[data-gallery-stage]');
      var mainImg = root.querySelector('[data-gallery-main]');
      var thumbs = Array.prototype.slice.call(root.querySelectorAll('.rb-thumb'));
      var indicator = root.querySelector('[data-gallery-indicator]');
      var spinToggle = root.querySelector('[data-spin-toggle]');
      var spinAutoBtn = root.querySelector('[data-spin-auto]');
      var spinHint = root.querySelector('[data-spin-hint]');

      if (!stage || !mainImg) return;

      var frames = thumbs.length
        ? thumbs.map(function (t) { return t.getAttribute('data-src'); })
        : [mainImg.getAttribute('src')];
      var frameIdx = 0;
      var spinMode = false;
      var autoSpinTimer = null;
      var dragging = false;
      var lastX = 0;
      var dragAccum = 0;

      // Preload angle frames smoothly once 360° spin is enabled
      var preloaded = false;
      function preloadFrames() {
        if (preloaded) return;
        preloaded = true;
        frames.forEach(function (src) {
          if (!src) return;
          var im = new Image();
          im.src = src;
        });
      }

      function setFrame(idx, instant) {
        var next = ((idx % frames.length) + frames.length) % frames.length;
        frameIdx = next;
        var src = frames[next];
        if (!src) return;

        if (instant || prefersReducedMotion()) {
          mainImg.src = src;
        } else {
          mainImg.classList.add('is-fading');
          setTimeout(function () {
            mainImg.src = src;
            mainImg.classList.remove('is-fading');
          }, 110);
        }

        thumbs.forEach(function (t, i) {
          var on = i === next;
          t.classList.toggle('active', on);
          t.setAttribute('aria-selected', on ? 'true' : 'false');
        });

        if (indicator) {
          if (spinMode) {
            var deg = Math.round((next / frames.length) * 360);
            indicator.textContent = deg + '° · ' + (next + 1) + ' / ' + frames.length;
          } else if (frames.length > 1) {
            indicator.textContent = (next + 1) + ' / ' + frames.length;
          }
        }
      }

      thumbs.forEach(function (t, i) {
        t.addEventListener('click', function () {
          stopAutoSpin();
          setFrame(i, false);
        });
      });

      // Smooth cursor zoom when NOT in 360° spin mode
      var finePointer = window.matchMedia && window.matchMedia('(hover: hover) and (pointer: fine)').matches;
      if (finePointer) {
        stage.addEventListener('mousemove', function (e) {
          if (spinMode || prefersReducedMotion()) return;
          var rect = stage.getBoundingClientRect();
          var x = ((e.clientX - rect.left) / rect.width) * 100;
          var y = ((e.clientY - rect.top) / rect.height) * 100;
          mainImg.style.transformOrigin = x.toFixed(1) + '% ' + y.toFixed(1) + '%';
          stage.classList.add('is-zooming');
        });
        stage.addEventListener('mouseleave', function () {
          stage.classList.remove('is-zooming');
          mainImg.style.transformOrigin = '50% 50%';
        });
      }

      function stopAutoSpin() {
        if (autoSpinTimer) {
          clearInterval(autoSpinTimer);
          autoSpinTimer = null;
        }
        if (spinAutoBtn) {
          spinAutoBtn.setAttribute('aria-pressed', 'false');
          var lbl = spinAutoBtn.querySelector('[data-spin-auto-label]');
          if (lbl) lbl.textContent = 'Auto-spin';
        }
      }

      function toggleAutoSpin() {
        if (autoSpinTimer) {
          stopAutoSpin();
          return;
        }
        if (prefersReducedMotion()) return;
        preloadFrames();
        if (spinAutoBtn) {
          spinAutoBtn.setAttribute('aria-pressed', 'true');
          var lbl = spinAutoBtn.querySelector('[data-spin-auto-label]');
          if (lbl) lbl.textContent = 'Pause spin';
        }
        autoSpinTimer = setInterval(function () {
          if (!document.hidden) setFrame(frameIdx + 1, true);
        }, timing.spinMs * 2);
      }

      if (spinToggle && frames.length >= 3) {
        spinToggle.addEventListener('click', function () {
          spinMode = !spinMode;
          spinToggle.setAttribute('aria-pressed', spinMode ? 'true' : 'false');
          stage.classList.toggle('is-spin-mode', spinMode);
          stage.classList.remove('is-zooming');
          if (spinAutoBtn) spinAutoBtn.hidden = !spinMode;
          if (spinHint) spinHint.hidden = !spinMode;
          if (spinMode) {
            preloadFrames();
            setFrame(frameIdx, true);
          } else {
            stopAutoSpin();
            setFrame(frameIdx, true);
          }
        });
      }

      if (spinAutoBtn) {
        spinAutoBtn.addEventListener('click', toggleAutoSpin);
      }

      stage.addEventListener('pointerdown', function (e) {
        if (!spinMode || e.target.closest('button')) return;
        dragging = true;
        lastX = e.clientX;
        dragAccum = 0;
        stage.classList.add('is-dragging');
        stopAutoSpin();
        if (stage.setPointerCapture) {
          try { stage.setPointerCapture(e.pointerId); } catch (err) { /* noop */ }
        }
      });

      stage.addEventListener('pointermove', function (e) {
        if (!dragging || !spinMode) return;
        var dx = e.clientX - lastX;
        lastX = e.clientX;
        dragAccum += dx;
        var stepPx = Math.max(24, Math.floor((stage.clientWidth || 360) / (frames.length * 1.6)));
        if (Math.abs(dragAccum) >= stepPx) {
          var steps = Math.trunc(dragAccum / stepPx);
          dragAccum -= steps * stepPx;
          setFrame(frameIdx + steps, true);
        }
      });

      function endDrag() {
        dragging = false;
        stage.classList.remove('is-dragging');
      }
      stage.addEventListener('pointerup', endDrag);
      stage.addEventListener('pointercancel', endDrag);

      stage.addEventListener('keydown', function (e) {
        if (frames.length <= 1) return;
        if (e.key === 'ArrowLeft') { e.preventDefault(); stopAutoSpin(); setFrame(frameIdx - 1, spinMode); }
        else if (e.key === 'ArrowRight') { e.preventDefault(); stopAutoSpin(); setFrame(frameIdx + 1, spinMode); }
      });

      document.addEventListener('visibilitychange', function () {
        if (document.hidden) stopAutoSpin();
      });
    });
  }

  /* --------------------------------------------------------------------------
     7. ACCESSIBLE QUICK-VIEW MODAL (Works from every animated section)
     -------------------------------------------------------------------------- */
  function initQuickView() {
    var modal = document.getElementById('rbQuickViewModal');
    if (!modal) return;

    var img = document.getElementById('rbQvImg');
    var placeholder = document.getElementById('rbQvPlaceholder');
    var discountEl = document.getElementById('rbQvDiscount');
    var catEl = document.getElementById('rbQvCategory');
    var titleEl = document.getElementById('rbQvTitle');
    var priceEl = document.getElementById('rbQvPrice');
    var oldPriceEl = document.getElementById('rbQvOldPrice');
    var stockEl = document.getElementById('rbQvStock');
    var descEl = document.getElementById('rbQvDesc');
    var cartForm = document.getElementById('rbQvCartForm');
    var qtyInput = document.getElementById('rbQvQty');
    var addBtn = document.getElementById('rbQvAddBtn');
    var fullLink = document.getElementById('rbQvFullLink');
    var lastTrigger = null;

    function closeQv() {
      modal.classList.remove('open');
      modal.setAttribute('aria-hidden', 'true');
      document.body.style.overflow = '';
      if (lastTrigger && lastTrigger.focus) lastTrigger.focus();
    }

    function openQv(btn) {
      lastTrigger = btn;
      var src = btn.getAttribute('data-qv-image') || '';
      var name = btn.getAttribute('data-qv-name') || '';
      var cat = btn.getAttribute('data-qv-category') || '';
      var price = btn.getAttribute('data-qv-price') || '';
      var oldPrice = btn.getAttribute('data-qv-old-price') || '';
      var discount = btn.getAttribute('data-qv-discount') || '';
      var url = btn.getAttribute('data-qv-url') || '#';
      var cartUrl = btn.getAttribute('data-qv-cart-url') || '#';
      var stock = parseInt(btn.getAttribute('data-qv-stock') || '0', 10) || 0;
      var isOut = btn.getAttribute('data-qv-out') === '1';
      var desc = btn.getAttribute('data-qv-desc') || '';

      if (src && img) {
        img.src = src;
        img.alt = name;
        img.hidden = false;
        if (placeholder) placeholder.hidden = true;
      } else {
        if (img) img.hidden = true;
        if (placeholder) placeholder.hidden = false;
      }

      if (discountEl) {
        if (discount) {
          discountEl.textContent = '-' + discount + '%';
          discountEl.hidden = false;
        } else {
          discountEl.hidden = true;
        }
      }

      if (catEl) catEl.textContent = cat;
      if (titleEl) titleEl.textContent = name;
      if (priceEl) priceEl.textContent = price;
      if (oldPriceEl) {
        oldPriceEl.textContent = oldPrice;
        oldPriceEl.hidden = !oldPrice;
      }
      if (stockEl) {
        stockEl.textContent = isOut ? 'Out of stock' : (stock <= 5 ? 'Low stock — ' + stock + ' left' : 'In stock');
        stockEl.style.color = isOut ? 'var(--bad)' : (stock <= 5 ? 'var(--warn)' : 'var(--ok)');
      }
      if (descEl) descEl.textContent = desc;
      if (cartForm) cartForm.action = cartUrl;
      if (qtyInput) {
        qtyInput.value = '1';
        qtyInput.max = String(Math.max(1, stock));
      }
      if (addBtn) {
        addBtn.disabled = isOut;
        addBtn.classList.remove('is-loading');
        addBtn.textContent = isOut ? 'Out of stock' : 'Add to cart';
      }
      if (fullLink) fullLink.href = url;

      modal.classList.add('open');
      modal.setAttribute('aria-hidden', 'false');
      document.body.style.overflow = 'hidden';
      var closeBtn = modal.querySelector('[data-qv-close]');
      if (closeBtn) setTimeout(function () { closeBtn.focus(); }, 40);
    }

    document.addEventListener('click', function (e) {
      var btn = e.target.closest ? e.target.closest('[data-quick-view]') : null;
      if (btn) {
        e.preventDefault();
        e.stopPropagation();
        openQv(btn);
        return;
      }
      if (e.target === modal || (e.target.closest && e.target.closest('[data-qv-close]'))) {
        closeQv();
      }
    });

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && modal.classList.contains('open')) {
        closeQv();
      }
    });
  }

  function boot() {
    initHeroSliders();
    initCoverflows();
    initMarquees();
    initTiltCards();
    initScrollReveal();
    initProductGalleries();
    initQuickView();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
