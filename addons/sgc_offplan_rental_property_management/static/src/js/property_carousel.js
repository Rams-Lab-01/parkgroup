/** @odoo-module **/

// Property Carousel — thumbnail strip drives the main Bootstrap carousel.
// Rewritten from legacy odoo.define() (rejected by Odoo 19's loader) to the
// modern @odoo-module form used elsewhere in this addon.

document.addEventListener('DOMContentLoaded', function () {
    // Click on a thumbnail jumps the main carousel to that slide and
    // marks the thumbnail as active.
    document.addEventListener('click', function (ev) {
        var thumb = ev.target.closest('.thumb-img');
        if (!thumb) {
            return;
        }
        var targetSel = thumb.getAttribute('data-bs-target') || '#propertyCarousel';
        var carousel = document.querySelector(targetSel);
        if (!carousel) {
            return;
        }
        var slideTo = parseInt(thumb.getAttribute('data-bs-slide-to'), 10);
        if (!isNaN(slideTo) && window.jQuery && window.jQuery(carousel).carousel) {
            // Bootstrap's jQuery carousel plugin (still shipped on the
            // website frontend in Odoo 19) handles the slide transition.
            window.jQuery(carousel).carousel(slideTo);
        }
        // Reflect the active thumbnail in the strip regardless of the
        // main carousel's underlying library.
        var strip = thumb.closest('.thumbnail-strip');
        if (strip) {
            strip.querySelectorAll('.thumb-img').forEach(function (el) {
                el.classList.remove('active-thumb');
            });
        }
        thumb.classList.add('active-thumb');
    });

    // Bootstrap 4 fires `slide.bs.carousel` with {relatedTarget, to, from,
    // direction}; we only need `to` to highlight the matching thumbnail.
    // Bootstrap 5 dropped this event but does not break anything here — the
    // click handler above keeps the strip in sync.
    document.addEventListener('slide.bs.carousel', function (ev) {
        var carousel = ev.target;
        if (!carousel || carousel.id !== 'propertyCarousel') {
            return;
        }
        var idx = ev.to;
        var thumbs = carousel.querySelectorAll('.thumb-img');
        thumbs.forEach(function (el, i) {
            el.classList.toggle('active-thumb', i === idx);
        });
    });
});