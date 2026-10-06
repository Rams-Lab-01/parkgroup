/** @odoo-module **/
/**
 * ListRenderer querySelector Error Fix
 * 
 * Fixes: TypeError: Cannot read properties of null (reading 'querySelector')
 * at ListRenderer.onGlobalClick
 * 
 * This error occurs when Odoo's ListRenderer tries to access DOM elements
 * that haven't been rendered yet or have been removed.
 */

import { ListRenderer } from "@web/views/list/list_renderer";
import { patch } from "@web/core/utils/patch";

// Store original onGlobalClick method
const originalOnGlobalClick = ListRenderer.prototype.onGlobalClick;

patch(ListRenderer.prototype, {
    /**
     * Patched onGlobalClick with null safety checks
     * Prevents errors when DOM elements are not available
     */
    onGlobalClick(ev) {
        try {
            // Add null safety check for the root element
            if (!this.rootRef || !this.rootRef.el) {
                console.warn('[rental_management] ListRenderer: Root element not available');
                return;
            }

            // Add null safety check for querySelector
            const rootEl = this.rootRef.el;
            if (!rootEl.querySelector) {
                console.warn('[rental_management] ListRenderer: querySelector not available');
                return;
            }

            // Check if the click target is valid
            if (!ev || !ev.target) {
                return;
            }

            // Call original method with try-catch wrapper
            if (originalOnGlobalClick) {
                originalOnGlobalClick.call(this, ev);
            }
        } catch (error) {
            // Tolerate ONLY the failure this patch exists for: the null
            // querySelector. The previous blanket catch swallowed every error in
            // onGlobalClick, which meant any genuine regression in that method was
            // invisible in production. Anything else propagates as it would
            // without this patch.
            const message = (error && error.message) || "";
            if (error instanceof TypeError && /querySelector/.test(message)) {
                console.warn(
                    '[rental_management] ListRenderer.onGlobalClick: tolerated null querySelector',
                    message
                );
                return;
            }
            throw error;
        }
    },
});

console.log('[rental_management] ListRenderer querySelector fix loaded');
