/** @odoo-module **/

import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { ListRenderer } from "@web/views/list/list_renderer";
import { RentalPropertyDashboard } from '@sgc_offplan_rental_property_management/components/rental_property_dashboard';

export class RentalPropertyDashboardRenderer extends ListRenderer {};

RentalPropertyDashboardRenderer.template = 'sgc_offplan_rental_property_management.RentalPropertyListView';
RentalPropertyDashboardRenderer.components= Object.assign({}, ListRenderer.components, {RentalPropertyDashboard})

export const RentalPropertyDashboardListView = {
    ...listView,
    Renderer: RentalPropertyDashboardRenderer,
};

registry.category("views").add("rental_property_dashboard_list", RentalPropertyDashboardListView);