/** @odoo-module **/
// Copyright 2026 SGC TECH AI
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class SgcRealEstateDashboard extends Component {
    static template = "sgc_realestate_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true, error: null });
        onWillStart(async () => {
            await this.load();
        });
    }

    async load() {
        try {
            this.state.data = await this.orm.call(
                "sgc.realestate.dashboard", "get_dashboard_data", []);
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async openRecords(kind, params = {}) {
        const action = await this.orm.call(
            "sgc.realestate.dashboard", "open_records", [kind, params]);
        if (action) {
            this.action.doAction(action);
        }
    }

    fmt(value) {
        return new Intl.NumberFormat("en-AE", {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        }).format(value || 0);
    }
}

registry.category("actions").add("sgc_realestate_dashboard", SgcRealEstateDashboard);
