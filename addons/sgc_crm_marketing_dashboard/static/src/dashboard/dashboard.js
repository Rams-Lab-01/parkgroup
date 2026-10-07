/** @odoo-module **/
// Copyright 2026 SGC TECH AI
import { registry } from "@web/core/registry";
import { Component, onWillStart, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

export class SgcCrmMarketingDashboard extends Component {
    static template = "sgc_crm_marketing_dashboard.Dashboard";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: true, error: null, period: "month" });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.data = await this.orm.call(
                "sgc.crm.marketing.dashboard", "get_dashboard_data", [this.state.period]);
        } catch (e) {
            this.state.error = e.message || String(e);
        } finally {
            this.state.loading = false;
        }
    }

    async setPeriod(period) {
        this.state.period = period;
        await this.load();
    }

    async openRecords(kind, params = {}) {
        const action = await this.orm.call(
            "sgc.crm.marketing.dashboard", "open_records", [kind, params]);
        if (action) {
            this.action.doAction(action);
        }
    }

    fmt(value) {
        return new Intl.NumberFormat("en-AE", {
            minimumFractionDigits: 0, maximumFractionDigits: 0,
        }).format(value || 0);
    }

    pct(value) {
        return (value == null ? "—" : value + "%");
    }
}

registry.category("actions").add("sgc_crm_marketing_dashboard", SgcCrmMarketingDashboard);
