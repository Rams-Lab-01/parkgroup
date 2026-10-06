/** @odoo-module **/

// Property Search Enhancement
document.addEventListener('DOMContentLoaded', function() {
    
    // Auto-submit search form on filter change
    const searchForm = document.querySelector('.o_property_search_form');
    if (searchForm) {
        const selects = searchForm.querySelectorAll('select');
        selects.forEach(select => {
            select.addEventListener('change', function() {
                // Optional: Auto-submit on change
                // searchForm.submit();
            });
        });
    }

    // Image lazy loading
    const propertyImages = document.querySelectorAll('.o_property_card img');
    if ('IntersectionObserver' in window) {
        const imageObserver = new IntersectionObserver((entries, observer) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const img = entry.target;
                    img.src = img.dataset.src || img.src;
                    img.classList.add('loaded');
                    imageObserver.unobserve(img);
                }
            });
        });

        propertyImages.forEach(img => imageObserver.observe(img));
    }

    // Smooth scroll for property detail sections
    const propertyLinks = document.querySelectorAll('a[href^="#"]');
    propertyLinks.forEach(link => {
        link.addEventListener('click', function(e) {
            const href = this.getAttribute('href');
            if (href !== '#') {
                e.preventDefault();
                const target = document.querySelector(href);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth' });
                }
            }
        });
    });

    // Form validation enhancement
    const contactForm = document.querySelector('form[action="/properties/contact"]');
    if (contactForm) {
        contactForm.addEventListener('submit', function(e) {
            const nameInput = this.querySelector('input[name="name"]');
            const emailInput = this.querySelector('input[name="email"]');
            
            if (!nameInput.value.trim()) {
                e.preventDefault();
                alert('Please enter your name');
                nameInput.focus();
                return false;
            }
            
            if (!emailInput.value.trim()) {
                e.preventDefault();
                alert('Please enter your email');
                emailInput.focus();
                return false;
            }
            
            const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
            if (!emailPattern.test(emailInput.value)) {
                e.preventDefault();
                alert('Please enter a valid email address');
                emailInput.focus();
                return false;
            }
        });
    }

    console.log('Property search initialized');
});
