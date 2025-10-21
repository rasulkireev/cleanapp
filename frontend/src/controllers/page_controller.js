import { Controller } from "@hotwired/stimulus";
import { showMessage } from "../utils/messages";

export default class extends Controller {
    static targets = ["checkbox", "selectAll", "bulkActions", "markNoReview", "markNeedsReview"];

    connect() {
        this.updateBulkActionsVisibility();
    }

    toggleSelectAll(event) {
        const checked = event.target.checked;
        this.checkboxTargets.forEach(checkbox => {
            checkbox.checked = checked;
        });
        this.updateBulkActionsVisibility();
    }

    toggleCheckbox() {
        const allChecked = this.checkboxTargets.every(checkbox => checkbox.checked);
        const anyChecked = this.checkboxTargets.some(checkbox => checkbox.checked);

        if (this.hasSelectAllTarget) {
            this.selectAllTarget.checked = allChecked;
            this.selectAllTarget.indeterminate = anyChecked && !allChecked;
        }

        this.updateBulkActionsVisibility();
    }

    updateBulkActionsVisibility() {
        const anyChecked = this.checkboxTargets.some(checkbox => checkbox.checked);

        if (this.hasBulkActionsTarget) {
            if (anyChecked) {
                this.bulkActionsTarget.classList.remove("hidden");
            } else {
                this.bulkActionsTarget.classList.add("hidden");
            }
        }
    }

    async markAsNoReview(event) {
        event.preventDefault();
        await this.updatePages(false);
    }

    async markAsNeedsReview(event) {
        event.preventDefault();
        await this.updatePages(true);
    }

    async updatePages(needsReview) {
        const selectedCheckboxes = this.checkboxTargets.filter(checkbox => checkbox.checked);
        const pageIds = selectedCheckboxes.map(checkbox => parseInt(checkbox.dataset.pageId));

        if (pageIds.length === 0) {
            showMessage("Please select at least one page", "error");
            return;
        }

        try {
            const response = await fetch("/api/pages/bulk-update", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": this.getCsrfToken()
                },
                body: JSON.stringify({
                    page_ids: pageIds,
                    needs_review: needsReview
                })
            });

            const data = await response.json();

            if (response.ok && data.success) {
                showMessage(data.message, "success");
                location.reload();
            } else {
                showMessage(data.message || "Failed to update pages", "error");
            }
        } catch (error) {
            console.error("Error updating pages:", error);
            showMessage("An error occurred while updating pages", "error");
        }
    }

    getCsrfToken() {
        return document.querySelector("[name=csrfmiddlewaretoken]").value;
    }
}
